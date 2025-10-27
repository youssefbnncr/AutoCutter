#!/usr/bin/env python3
"""
Renderer Module - Handles FFmpeg rendering operations
"""

import os
import subprocess
import logging
from datetime import datetime
from pathlib import Path


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FFmpegRenderer:
    """Handles FFmpeg rendering operations"""
    
    @staticmethod
    def check_encoder_available(encoder_name):
        """
        Check if specific encoder is available in FFmpeg
        
        Args:
            encoder_name: Name of encoder (e.g., 'h264_nvenc')
            
        Returns:
            bool: True if encoder is available
        """
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=5
            )
            return encoder_name in result.stdout
        except Exception as e:
            logger.error(f"Error checking encoder {encoder_name}: {e}")
            return False
    
    @staticmethod
    def get_best_codec(prefer_gpu=False):
        """
        Get best available codec
        
        Args:
            prefer_gpu: Whether to prefer GPU encoding
            
        Returns:
            str: Codec name ('h264_nvenc' or 'libx264')
        """
        if prefer_gpu and FFmpegRenderer.check_encoder_available("h264_nvenc"):
            logger.info("Using GPU encoder: h264_nvenc")
            return "h264_nvenc"
        
        logger.info("Using CPU encoder: libx264")
        return "libx264"
    
    @staticmethod
    def render_clip(
        segment_index,
        clip_length,
        animation_video,
        background_video,
        music_file,
        music_start,
        output_path,
        codec="libx264",
        use_loudnorm=False,
        log_dir=None
    ):
        """
        Render a single video clip
        
        Args:
            segment_index: Index of the segment
            clip_length: Length of clip in seconds
            animation_video: Path to animation/overlay video
            background_video: Path to background video
            music_file: Path to music file
            music_start: Start time in music file
            output_path: Output file path
            codec: Video codec to use
            use_loudnorm: Whether to apply audio normalization
            log_dir: Directory for log files
            
        Returns:
            tuple: (success: bool, message: str)
        """
        bg_start_time = segment_index * clip_length
        
        # Build FFmpeg command
        cmd = [
            "ffmpeg",
            "-y",
            # Animation video (overlay) - loop to ensure coverage
            "-stream_loop", "1",
            "-i", animation_video,
            # Background video - seek to specific segment
            "-ss", str(bg_start_time),
            "-t", str(clip_length),
            "-i", background_video,
            # Music - seek to user-specified start time
            "-ss", str(music_start),
            "-t", str(clip_length),
            "-i", music_file,
            # Filter complex: process animation and background, then overlay
            "-filter_complex",
            (
                f"[0:v]trim=duration={clip_length},setpts=PTS-STARTPTS,format=rgba[main];"
                f"[1:v]trim=duration={clip_length},setpts=PTS-STARTPTS,"
                f"crop=ih*9/16:ih,scale=1080:1920[bg];"
                "[bg][main]overlay=(W-w)/2:(H-h)/2:shortest=1[v]"
            ),
            "-map", "[v]",
            "-map", "2:a",  # Audio from music (input index 2)
            "-t", str(clip_length),
            "-c:v", codec,
            "-b:v", "3500k",
            "-pix_fmt", "yuv420p",
        ]
        
        # Audio processing
        if use_loudnorm:
            cmd += ["-af", "loudnorm=I=-16:LRA=11:TP=-1.5"]
        cmd += ["-c:a", "aac", "-b:a", "192k"]
        
        cmd.append(output_path)
        
        # Logging
        clip_name = os.path.basename(output_path)
        logger.info(f"Starting render: {clip_name}")
        
        log_path = None
        if log_dir:
            log_path = os.path.join(log_dir, f"{clip_name}.log")
        
        try:
            if log_path:
                with open(log_path, "w", encoding="utf-8") as logf:
                    logf.write("COMMAND:\n" + " ".join(cmd) + "\n\n")
                    logf.write(f"Started: {datetime.now()}\n\n")
                    
                    proc = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=clip_length * 20  # Generous timeout
                    )
                    
                    logf.write(proc.stdout)
                    logf.write(f"\n\nFinished: {datetime.now()}\n")
                    logf.write(f"Return code: {proc.returncode}\n")
                    
                    if proc.returncode != 0:
                        tail = "\n".join(proc.stdout.splitlines()[-20:])
                        logger.error(f"Failed to render {clip_name}")
                        return (False, f"❌ {clip_name} (see log: {log_path})")
                    
                    logger.info(f"Successfully rendered: {clip_name}")
                    return (True, f"✅ {clip_name}")
            else:
                # No logging
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=clip_length * 20
                )
                
                if proc.returncode != 0:
                    logger.error(f"Failed to render {clip_name}")
                    return (False, f"❌ {clip_name}")
                
                logger.info(f"Successfully rendered: {clip_name}")
                return (True, f"✅ {clip_name}")
                
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout rendering {clip_name}")
            return (False, f"❌ {clip_name} (timeout)")
        except Exception as e:
            logger.error(f"Exception rendering {clip_name}: {e}")
            return (False, f"❌ {clip_name} (error: {e})")


class RenderSession:
    """Manages a rendering session"""
    
    def __init__(self, output_base_dir="./output"):
        """
        Initialize render session
        
        Args:
            output_base_dir: Base directory for output
        """
        self.session_name = datetime.now().strftime("session_%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(output_base_dir, self.session_name)
        self.log_dir = os.path.join(self.session_dir, "logs")
        
        # Create directories
        os.makedirs(self.session_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)
        
        logger.info(f"Created session: {self.session_dir}")
    
    def generate_clip_filename(self, index, clip_length):
        """
        Generate filename for a clip
        
        Args:
            index: Clip index
            clip_length: Clip length in seconds
            
        Returns:
            str: Full path to output file
        """
        filename = f"clip_{index + 1:03d}_{clip_length}s.mp4"
        return os.path.join(self.session_dir, filename)
    
    def write_summary(self, settings, results):
        """
        Write session summary file
        
        Args:
            settings: Dictionary of rendering settings
            results: List of result messages
        """
        summary_path = os.path.join(self.session_dir, "summary.txt")
        
        try:
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(f"AutoCutter Render Session\n")
                f.write(f"=" * 50 + "\n\n")
                f.write(f"Session: {self.session_name}\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                f.write("Settings:\n")
                f.write("-" * 50 + "\n")
                for key, value in settings.items():
                    if isinstance(value, str) and os.path.exists(value):
                        value = os.path.basename(value)
                    f.write(f"{key}: {value}\n")
                
                f.write("\n" + "=" * 50 + "\n")
                f.write("Results:\n")
                f.write("-" * 50 + "\n")
                
                success_count = sum(1 for r in results if r.startswith("✅"))
                total = len(results)
                f.write(f"\nSuccess: {success_count}/{total}\n\n")
                
                for r in results:
                    f.write(r + "\n")
            
            logger.info(f"Summary written to: {summary_path}")
            
        except Exception as e:
            logger.error(f"Error writing summary: {e}")