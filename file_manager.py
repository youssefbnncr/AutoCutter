#!/usr/bin/env python3
"""
File Manager Module - Handles file operations and media information
"""

import os
import subprocess
from shutil import which
from pathlib import Path


class FileManager:
    """Manages file operations and media information retrieval"""
    
    @staticmethod
    def check_ffmpeg_available():
        """Check if ffmpeg and ffprobe are available in PATH"""
        return which("ffmpeg") is not None and which("ffprobe") is not None
    
    @staticmethod
    def get_media_duration(file_path):
        """
        Get duration of media file using ffprobe
        
        Args:
            file_path: Path to media file
            
        Returns:
            float: Duration in seconds, or 0 if error
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0",
                    file_path
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
            return 0
        except Exception as e:
            print(f"Error getting duration for {file_path}: {e}")
            return 0
    
    @staticmethod
    def get_video_resolution(file_path):
        """
        Get video resolution using ffprobe
        
        Args:
            file_path: Path to video file
            
        Returns:
            tuple: (width, height) or (0, 0) if error
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "csv=p=0",
                    file_path
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(',')
                if len(parts) == 2:
                    return int(parts[0]), int(parts[1])
            return 0, 0
        except Exception:
            return 0, 0
    
    @staticmethod
    def ensure_directory(path):
        """
        Ensure directory exists, create if not
        
        Args:
            path: Directory path
            
        Returns:
            bool: True if successful
        """
        try:
            os.makedirs(path, exist_ok=True)
            return True
        except Exception as e:
            print(f"Error creating directory {path}: {e}")
            return False
    
    @staticmethod
    def format_duration(seconds):
        """
        Format duration in seconds to human readable string
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            str: Formatted duration (e.g., "2m 30s")
        """
        if seconds <= 0:
            return "0s"
        
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or not parts:
            parts.append(f"{secs}s")
        
        return " ".join(parts)
    
    @staticmethod
    def validate_file_exists(file_path):
        """
        Check if file exists and is readable
        
        Args:
            file_path: Path to file
            
        Returns:
            bool: True if file exists and is readable
        """
        if not file_path:
            return False
        
        path = Path(file_path)
        return path.exists() and path.is_file() and os.access(file_path, os.R_OK)
    
    @staticmethod
    def get_file_size(file_path):
        """
        Get file size in bytes
        
        Args:
            file_path: Path to file
            
        Returns:
            int: File size in bytes, or 0 if error
        """
        try:
            return os.path.getsize(file_path)
        except Exception:
            return 0
    
    @staticmethod
    def format_file_size(bytes_size):
        """
        Format file size to human readable string
        
        Args:
            bytes_size: Size in bytes
            
        Returns:
            str: Formatted size (e.g., "1.5 MB")
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} PB"