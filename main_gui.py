#!/usr/bin/env python3
"""
AutoCutter GUI - Complete implementation with rendering
Requires: PySide6 only (uses ffprobe for media info)
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from shutil import which
from concurrent.futures import ProcessPoolExecutor, as_completed

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QSpinBox, QProgressBar,
    QGroupBox, QMessageBox, QCheckBox, QLineEdit, QDoubleSpinBox,
    QSlider, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


def get_media_duration(file_path):
    """Get duration of media file using ffprobe"""
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
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        return 0
    except Exception as e:
        print(f"Error getting duration: {e}")
        return 0


def ffmpeg_has_encoder(name):
    """Check if ffmpeg has specific encoder"""
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False
        )
        return name in r.stdout
    except Exception:
        return False


def render_segment(segment_info):
    """
    Render a single video segment
    segment_info: (segment_index, clip_length, main_video, bg_video, music_file, 
                   music_start, output_path, codec, use_loudnorm, log_dir)
    """
    (
        segment,
        clip_length,
        main_video,
        bg_video,
        music_file,
        music_start,
        output_path,
        codec,
        use_loudnorm,
        log_dir,
    ) = segment_info
    
    bg_start_time = segment * clip_length

    # Build FFmpeg command
    cmd = [
        "ffmpeg",
        "-y",
        # Main video (animation/overlay) - loop to ensure coverage
        "-stream_loop", "1",
        "-i", main_video,
        # Background video - seek to specific segment
        "-ss", str(bg_start_time),
        "-t", str(clip_length),
        "-i", bg_video,
        # Music - seek to user-specified start time
        "-ss", str(music_start),
        "-t", str(clip_length),
        "-i", music_file,
        # Filter complex: process main and bg, then overlay
        "-filter_complex",
        (
            f"[0:v]trim=duration={clip_length},setpts=PTS-STARTPTS,format=rgba[main];"
            f"[1:v]trim=duration={clip_length},setpts=PTS-STARTPTS,crop=ih*9/16:ih,scale=1080:1920[bg];"
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

    # Log file for this clip
    clip_name = os.path.basename(output_path)
    log_path = os.path.join(log_dir, f"{clip_name}.log")
    
    try:
        with open(log_path, "w", encoding="utf-8") as logf:
            logf.write("COMMAND:\n" + " ".join(cmd) + "\n\n")
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            logf.write(proc.stdout)
            
            if proc.returncode != 0:
                tail = "\n".join(proc.stdout.splitlines()[-20:])
                return (False, f"❌ {clip_name} failed. Last output:\n{tail}")
            return (True, f"✅ {clip_name}")
    except Exception as e:
        return (False, f"❌ {clip_name} exception: {e}")


class FilePickerWidget(QWidget):
    """Custom widget for file picking with label display"""
    def __init__(self, label_text, file_filter, parent=None):
        super().__init__(parent)
        self.file_path = None
        self.duration = 0
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Title label
        title = QLabel(label_text)
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        
        # Horizontal layout for file info and button
        h_layout = QHBoxLayout()
        
        # File info container
        info_container = QVBoxLayout()
        
        # File path display
        self.path_label = QLabel("No file selected")
        self.path_label.setStyleSheet("color: gray; padding: 5px; background: #f0f0f0; border-radius: 3px;")
        self.path_label.setWordWrap(True)
        self.path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info_container.addWidget(self.path_label)
        
        # Duration display
        self.duration_label = QLabel("Duration: --")
        info_container.addWidget(self.duration_label)
        
        h_layout.addLayout(info_container, stretch=1)
        
        # Pick button
        self.pick_button = QPushButton(f"Browse")
        self.pick_button.setFixedWidth(100)
        self.pick_button.clicked.connect(self.pick_file)
        h_layout.addWidget(self.pick_button)
        
        layout.addLayout(h_layout)
        
        self.file_filter = file_filter
        self.label_text = label_text
        
    def pick_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, f"Select {self.label_text}", "", self.file_filter
        )
        if file_path:
            self.set_file(file_path)
    
    def set_file(self, file_path):
        self.file_path = file_path
        filename = os.path.basename(file_path)
        self.path_label.setText(filename)
        self.path_label.setToolTip(file_path)
        self.path_label.setStyleSheet("color: green; padding: 5px; background: #e8f5e9; border-radius: 3px;")
        
        # Get duration using ffprobe
        self.duration = get_media_duration(file_path)
        
        if self.duration > 0:
            mins = int(self.duration // 60)
            secs = int(self.duration % 60)
            self.duration_label.setText(f"Duration: {mins}m {secs}s ({self.duration:.1f}s total)")
        else:
            self.duration_label.setText("Duration: Could not detect")


class MusicPlayerWidget(QWidget):
    """Music player with timeline for selecting start position"""
    position_changed = Signal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.music_duration = 0
        self.is_playing = False
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Media player setup
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.5)
        
        # Connect signals
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        
        # Timeline slider
        timeline_layout = QHBoxLayout()
        timeline_layout.addWidget(QLabel("Timeline:"))
        
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setRange(0, 1000)
        self.timeline_slider.setValue(0)
        self.timeline_slider.sliderPressed.connect(self.on_slider_pressed)
        self.timeline_slider.sliderReleased.connect(self.on_slider_released)
        self.timeline_slider.sliderMoved.connect(self.on_slider_moved)
        timeline_layout.addWidget(self.timeline_slider, stretch=1)
        
        layout.addLayout(timeline_layout)
        
        # Time display and controls
        controls_layout = QHBoxLayout()
        
        self.time_label = QLabel("0:00 / 0:00")
        controls_layout.addWidget(self.time_label)
        
        controls_layout.addStretch()
        
        # Play/Pause button
        self.play_button = QPushButton("▶ Play")
        self.play_button.setFixedWidth(80)
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setEnabled(False)
        controls_layout.addWidget(self.play_button)
        
        # Stop button
        self.stop_button = QPushButton("⏹ Stop")
        self.stop_button.setFixedWidth(80)
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        controls_layout.addWidget(self.stop_button)
        
        # Set start button
        self.set_start_button = QPushButton("📍 Set as Start")
        self.set_start_button.setFixedWidth(120)
        self.set_start_button.clicked.connect(self.set_start_position)
        self.set_start_button.setEnabled(False)
        controls_layout.addWidget(self.set_start_button)
        
        layout.addLayout(controls_layout)
        
        self.slider_pressed = False
    
    def load_music(self, file_path):
        """Load music file into player"""
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.set_start_button.setEnabled(True)
    
    def toggle_play(self):
        """Toggle play/pause"""
        if self.is_playing:
            self.player.pause()
            self.play_button.setText("▶ Play")
            self.is_playing = False
        else:
            self.player.play()
            self.play_button.setText("⏸ Pause")
            self.is_playing = True
    
    def stop(self):
        """Stop playback"""
        self.player.stop()
        self.play_button.setText("▶ Play")
        self.is_playing = False
        self.timeline_slider.setValue(0)
    
    def on_position_changed(self, position):
        """Update slider and time label when position changes"""
        if not self.slider_pressed and self.music_duration > 0:
            value = int((position / self.music_duration) * 1000)
            self.timeline_slider.setValue(value)
        
        current = position / 1000.0
        total = self.music_duration / 1000.0
        self.time_label.setText(
            f"{int(current//60)}:{int(current%60):02d} / {int(total//60)}:{int(total%60):02d}"
        )
    
    def on_duration_changed(self, duration):
        """Store music duration"""
        self.music_duration = duration
    
    def on_slider_pressed(self):
        """Mark slider as being dragged"""
        self.slider_pressed = True
    
    def on_slider_moved(self, value):
        """Update time label while dragging"""
        if self.music_duration > 0:
            position = (value / 1000.0) * self.music_duration
            current = position / 1000.0
            total = self.music_duration / 1000.0
            self.time_label.setText(
                f"{int(current//60)}:{int(current%60):02d} / {int(total//60)}:{int(total%60):02d}"
            )
    
    def on_slider_released(self):
        """Seek to position when slider is released"""
        self.slider_pressed = False
        if self.music_duration > 0:
            position = int((self.timeline_slider.value() / 1000.0) * self.music_duration)
            self.player.setPosition(position)
    
    def set_start_position(self):
        """Emit current position as start position"""
        if self.music_duration > 0:
            current_pos = (self.timeline_slider.value() / 1000.0) * (self.music_duration / 1000.0)
            self.position_changed.emit(current_pos)
    
    def get_current_position(self):
        """Get current position in seconds"""
        if self.music_duration > 0:
            return (self.timeline_slider.value() / 1000.0) * (self.music_duration / 1000.0)
        return 0


class RenderWorker(QThread):
    """Background thread for rendering clips"""
    progress = Signal(int, str)  # progress percentage, current clip name
    finished = Signal(str, list)  # success message, list of results
    error = Signal(str)
    
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
    
    def run(self):
        try:
            # Create session folder
            session_name = datetime.now().strftime("session_%Y-%m-%d_%H-%M-%S")
            output_dir = self.settings['output_dir']
            session_dir = os.path.join(output_dir, session_name)
            os.makedirs(session_dir, exist_ok=True)
            
            log_dir = os.path.join(session_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            
            # Build task list
            tasks = []
            bg_video = self.settings['background_video']
            num_clips = self.settings['num_clips']
            clip_length = self.settings['clip_length']
            
            for seg in range(num_clips):
                outname = f"clip_{seg + 1:03d}_{clip_length}s.mp4"
                outpath = os.path.join(session_dir, outname)
                tasks.append((
                    seg,
                    clip_length,
                    self.settings['animation_video'],
                    bg_video,
                    self.settings['music_file'],
                    self.settings['music_start'],
                    outpath,
                    self.settings['codec'],
                    self.settings['normalize_audio'],
                    log_dir,
                ))
            
            # Render in parallel
            results = []
            completed = 0
            workers = self.settings['workers']
            
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(render_segment, t): t for t in tasks}
                
                for future in as_completed(futures):
                    try:
                        success, msg = future.result()
                        results.append(msg)
                        completed += 1
                        progress = int((completed / len(tasks)) * 100)
                        self.progress.emit(progress, msg)
                    except Exception as e:
                        results.append(f"❌ Exception: {e}")
                        completed += 1
                        progress = int((completed / len(tasks)) * 100)
                        self.progress.emit(progress, f"❌ Error")
            
            # Write summary
            summary_file = os.path.join(session_dir, "summary.txt")
            with open(summary_file, "w", encoding="utf-8") as sf:
                sf.write(f"Session: {session_name}\n")
                sf.write(f"Background: {bg_video}\n")
                sf.write(f"Animation: {self.settings['animation_video']}\n")
                sf.write(f"Music: {self.settings['music_file']}\n")
                sf.write(f"Music Start: {self.settings['music_start']}s\n")
                sf.write(f"Clip Length: {clip_length}s\n")
                sf.write(f"Number of Clips: {num_clips}\n")
                sf.write(f"Codec: {self.settings['codec']}\n")
                sf.write(f"Audio Normalization: {self.settings['normalize_audio']}\n\n")
                sf.write("Results:\n")
                for r in results:
                    sf.write(r + "\n")
            
            success_count = sum(1 for r in results if r.startswith("✅"))
            final_msg = f"Rendered {success_count}/{len(tasks)} clips successfully!\n\nOutput: {session_dir}"
            
            self.finished.emit(final_msg, results)
            
        except Exception as e:
            self.error.emit(str(e))


class AutoCutterGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoCutter - Video Clip Generator")
        self.resize(800, 900)
        
        # Check for ffmpeg/ffprobe
        if not self.check_ffmpeg():
            QMessageBox.critical(
                self,
                "FFmpeg Not Found",
                "FFmpeg and FFprobe are required but not found in your system PATH.\n\n"
                "Please install FFmpeg:\n"
                "1. Download from: https://ffmpeg.org/download.html\n"
                "2. Add to your system PATH\n"
                "3. Restart this application"
            )
            sys.exit(1)
        
        # Central widget with scroll area
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(15)
        
        # Title
        title = QLabel("🎬 AutoCutter - Automated Video Clip Generator")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # === FILE INPUTS GROUP ===
        files_group = QGroupBox("📁 Input Files")
        files_layout = QVBoxLayout()
        
        # Background video picker
        self.bg_picker = FilePickerWidget(
            "Background Video",
            "Videos (*.mp4 *.mov *.mkv *.avi *.webm)"
        )
        self.bg_picker.pick_button.clicked.connect(self.on_background_changed)
        files_layout.addWidget(self.bg_picker)
        
        # Animation video picker
        self.anim_picker = FilePickerWidget(
            "Animation/Overlay Video",
            "Videos (*.mov *.mp4 *.mkv *.webm)"
        )
        self.anim_picker.pick_button.clicked.connect(self.on_animation_changed)
        files_layout.addWidget(self.anim_picker)
        
        # Music picker
        self.music_picker = FilePickerWidget(
            "Music/Audio",
            "Audio (*.mp3 *.wav *.aac *.m4a *.ogg)"
        )
        self.music_picker.pick_button.clicked.connect(self.on_music_changed)
        files_layout.addWidget(self.music_picker)
        
        files_group.setLayout(files_layout)
        main_layout.addWidget(files_group)
        
        # === CLIP SETTINGS GROUP ===
        settings_group = QGroupBox("⚙️ Clip Settings")
        settings_layout = QVBoxLayout()
        
        # Clip length
        clip_length_layout = QHBoxLayout()
        clip_length_layout.addWidget(QLabel("Clip Length (seconds):"))
        self.clip_length_spin = QSpinBox()
        self.clip_length_spin.setRange(1, 60)
        self.clip_length_spin.setValue(10)
        self.clip_length_spin.setFixedWidth(100)
        self.clip_length_spin.valueChanged.connect(self.update_calculations)
        clip_length_layout.addWidget(self.clip_length_spin)
        clip_length_layout.addWidget(QLabel("(Max based on animation duration)"))
        clip_length_layout.addStretch()
        settings_layout.addLayout(clip_length_layout)
        
        # Max clips info
        self.max_clips_label = QLabel("Maximum possible clips: --")
        self.max_clips_label.setStyleSheet("color: blue; font-weight: bold;")
        settings_layout.addWidget(self.max_clips_label)
        
        # Number of clips to generate
        num_clips_layout = QHBoxLayout()
        num_clips_layout.addWidget(QLabel("Number of clips to generate:"))
        self.num_clips_spin = QSpinBox()
        self.num_clips_spin.setRange(1, 1000)
        self.num_clips_spin.setValue(1)
        self.num_clips_spin.setFixedWidth(100)
        num_clips_layout.addWidget(self.num_clips_spin)
        num_clips_layout.addStretch()
        settings_layout.addLayout(num_clips_layout)
        
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)
        
        # === MUSIC TIMING GROUP ===
        music_group = QGroupBox("🎵 Music Selection & Preview")
        music_layout = QVBoxLayout()
        
        music_info = QLabel("Play music and set the start position for your clips:")
        music_info.setWordWrap(True)
        music_layout.addWidget(music_info)
        
        # Music player widget
        self.music_player = MusicPlayerWidget()
        self.music_player.position_changed.connect(self.on_music_position_set)
        music_layout.addWidget(self.music_player)
        
        # Music start time (manual input)
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("Start time (seconds):"))
        self.music_start_spin = QDoubleSpinBox()
        self.music_start_spin.setRange(0, 10000)
        self.music_start_spin.setValue(0)
        self.music_start_spin.setDecimals(1)
        self.music_start_spin.setSingleStep(0.5)
        self.music_start_spin.setFixedWidth(100)
        self.music_start_spin.valueChanged.connect(self.update_music_end)
        start_layout.addWidget(self.music_start_spin)
        start_layout.addStretch()
        music_layout.addLayout(start_layout)
        
        # Music end time (auto-calculated)
        self.music_end_label = QLabel("End time: 10.0s (Duration: 10.0s)")
        self.music_end_label.setStyleSheet("color: green;")
        music_layout.addWidget(self.music_end_label)
        
        music_group.setLayout(music_layout)
        main_layout.addWidget(music_group)
        
        # === ADVANCED OPTIONS ===
        advanced_group = QGroupBox("🔧 Advanced Options")
        advanced_layout = QVBoxLayout()
        
        self.gpu_checkbox = QCheckBox("Use GPU encoding (NVENC) if available")
        self.gpu_checkbox.setChecked(False)
        advanced_layout.addWidget(self.gpu_checkbox)
        
        self.normalize_checkbox = QCheckBox("Apply audio normalization (loudnorm)")
        self.normalize_checkbox.setChecked(True)
        advanced_layout.addWidget(self.normalize_checkbox)
        
        # Workers
        workers_layout = QHBoxLayout()
        workers_layout.addWidget(QLabel("Parallel workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, os.cpu_count() or 4)
        self.workers_spin.setValue(max(1, (os.cpu_count() or 2) // 2))
        self.workers_spin.setFixedWidth(100)
        workers_layout.addWidget(self.workers_spin)
        workers_layout.addStretch()
        advanced_layout.addLayout(workers_layout)
        
        advanced_group.setLayout(advanced_layout)
        main_layout.addWidget(advanced_group)
        
        # === OUTPUT ===
        output_group = QGroupBox("📤 Output")
        output_layout = QVBoxLayout()
        
        output_dir_layout = QHBoxLayout()
        output_dir_layout.addWidget(QLabel("Output folder:"))
        self.output_dir_edit = QLineEdit("./rendered")
        output_dir_layout.addWidget(self.output_dir_edit)
        browse_output_btn = QPushButton("Browse")
        browse_output_btn.setFixedWidth(100)
        browse_output_btn.clicked.connect(self.browse_output_dir)
        output_dir_layout.addWidget(browse_output_btn)
        output_layout.addLayout(output_dir_layout)
        
        output_group.setLayout(output_layout)
        main_layout.addWidget(output_group)
        
        # === PROGRESS ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        main_layout.addWidget(self.status_label)
        
        # === ACTION BUTTONS ===
        button_layout = QHBoxLayout()
        
        self.render_button = QPushButton("🚀 Start Rendering")
        self.render_button.setMinimumHeight(50)
        self.render_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.render_button.clicked.connect(self.start_rendering)
        button_layout.addWidget(self.render_button)
        
        main_layout.addLayout(button_layout)
        
        # Initialize
        self.update_calculations()
    
    def check_ffmpeg(self):
        """Check if ffmpeg and ffprobe are available"""
        return which("ffmpeg") is not None and which("ffprobe") is not None
    
    def on_background_changed(self):
        """Called when background video is selected"""
        self.update_calculations()
    
    def on_animation_changed(self):
        """Called when animation video is selected"""
        if self.anim_picker.duration > 0:
            max_duration = int(self.anim_picker.duration)
            self.clip_length_spin.setMaximum(max_duration)
            if self.clip_length_spin.value() > max_duration:
                self.clip_length_spin.setValue(max_duration)
        self.update_calculations()
    
    def on_music_changed(self):
        """Called when music file is selected"""
        if self.music_picker.file_path:
            self.music_player.load_music(self.music_picker.file_path)
        self.update_music_end()
    
    def on_music_position_set(self, position):
        """Called when user sets start position from player"""
        self.music_start_spin.setValue(position)
        QMessageBox.information(
            self,
            "Start Position Set",
            f"Music start position set to {position:.1f} seconds"
        )
    
    def update_calculations(self):
        """Update max possible clips calculation"""
        bg_duration = self.bg_picker.duration
        clip_length = self.clip_length_spin.value()
        
        if bg_duration > 0 and clip_length > 0:
            max_clips = int(bg_duration // clip_length)
            self.max_clips_label.setText(f"Maximum possible clips: {max_clips}")
            self.num_clips_spin.setMaximum(max_clips if max_clips > 0 else 1)
            if self.num_clips_spin.value() > max_clips:
                self.num_clips_spin.setValue(max_clips if max_clips > 0 else 1)
        else:
            self.max_clips_label.setText("Maximum possible clips: -- (select files first)")
        
        self.update_music_end()
    
    def update_music_end(self):
        """Update music end time display"""
        start = self.music_start_spin.value()
        duration = self.clip_length_spin.value()
        end = start + duration
        
        self.music_end_label.setText(f"End time: {end:.1f}s (Duration: {duration}s)")
        
        if self.music_picker.duration > 0:
            if end > self.music_picker.duration:
                self.music_end_label.setStyleSheet("color: red; font-weight: bold;")
                self.music_end_label.setText(
                    f"End time: {end:.1f}s ⚠️ EXCEEDS music duration ({self.music_picker.duration:.1f}s)!"
                )
            else:
                self.music_end_label.setStyleSheet("color: green;")
    
    def browse_output_dir(self):
        """Browse for output directory"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir_edit.setText(dir_path)
    
    def validate_inputs(self):
        """Validate all inputs before rendering"""
        errors = []
        
        if not self.bg_picker.file_path:
            errors.append("❌ Background video not selected")
        
        if not self.anim_picker.file_path:
            errors.append("❌ Animation video not selected")
        
        if not self.music_picker.file_path:
            errors.append("❌ Music file not selected")
        
        if self.anim_picker.duration > 0 and self.clip_length_spin.value() > self.anim_picker.duration:
            errors.append(f"❌ Clip length ({self.clip_length_spin.value()}s) exceeds animation duration ({self.anim_picker.duration:.1f}s)")
        
        if self.num_clips_spin.value() <= 0:
            errors.append("❌ Number of clips must be at least 1")
        
        music_end = self.music_start_spin.value() + self.clip_length_spin.value()
        if self.music_picker.duration > 0 and music_end > self.music_picker.duration:
            errors.append(f"❌ Music segment ({self.music_start_spin.value():.1f}s to {music_end:.1f}s) exceeds music duration ({self.music_picker.duration:.1f}s)")
        
        if self.bg_picker.duration > 0:
            bg_duration = self.bg_picker.duration
            clip_length = self.clip_length_spin.value()
            max_clips = int(bg_duration // clip_length)
            if self.num_clips_spin.value() > max_clips:
                errors.append(f"❌ Requested {self.num_clips_spin.value()} clips but only {max_clips} possible with {clip_length}s clips")
        
        return errors
    
    def start_rendering(self):
        """Start the rendering process"""
        errors = self.validate_inputs()
        
        if errors:
            QMessageBox.warning(
                self,
                "Validation Errors",
                "Please fix the following issues:\n\n" + "\n".join(errors)
            )
            return
        
        # Detect codec
        codec = "libx264"
        if self.gpu_checkbox.isChecked():
            if ffmpeg_has_encoder("h264_nvenc"):
                codec = "h264_nvenc"
            else:
                QMessageBox.warning(
                    self,
                    "GPU Encoding Unavailable",
                    "NVENC encoder not detected. Falling back to CPU encoding (libx264)."
                )
        
        # Prepare settings
        settings = {
            'background_video': self.bg_picker.file_path,
            'animation_video': self.anim_picker.file_path,
            'music_file': self.music_picker.file_path,
            'clip_length': self.clip_length_spin.value(),
            'num_clips': self.num_clips_spin.value(),
            'music_start': self.music_start_spin.value(),
            'music_end': self.music_start_spin.value() + self.clip_length_spin.value(),
            'codec': codec,
            'normalize_audio': self.normalize_checkbox.isChecked(),
            'workers': self.workers_spin.value(),
            'output_dir': self.output_dir_edit.text()
        }
        
        # Show confirmation
        confirm_msg = f"""
Ready to render with these settings:

📹 Background: {os.path.basename(settings['background_video'])}
🎨 Animation: {os.path.basename(settings['animation_video'])}
🎵 Music: {os.path.basename(settings['music_file'])}
⏱️ Clip Length: {settings['clip_length']}s
📊 Number of Clips: {settings['num_clips']}
🎼 Music Segment: {settings['music_start']:.1f}s - {settings['music_end']:.1f}s
🖥️ Codec: {codec}
🔊 Audio Normalization: {'Yes' if settings['normalize_audio'] else 'No'}
👷 Workers: {settings['workers']}

Estimated time: ~{settings['num_clips'] * settings['clip_length'] // settings['workers']} seconds

Proceed?
        """
        
        reply = QMessageBox.question(
            self,
            "Confirm Rendering",
            confirm_msg,
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.execute_render(settings)
    
    def execute_render(self, settings):
        """Execute the actual rendering"""
        # Stop music if playing
        self.music_player.stop()
        
        self.render_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("🔄 Initializing rendering...")
        
        # Create and start worker thread
        self.worker = RenderWorker(settings)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()
    
    def on_progress(self, value, clip_name):
        """Update progress bar"""
        self.progress_bar.setValue(value)
        self.status_label.setText(f"🔄 Rendering: {clip_name}")
    
    def on_finished(self, message, results):
        """Handle successful completion"""
        self.progress_bar.setVisible(False)
        self.status_label.setText("✅ Rendering complete!")
        self.render_button.setEnabled(True)
        
        # Show detailed results
        success_count = sum(1 for r in results if r.startswith("✅"))
        failed_count = len(results) - success_count
        
        result_text = message + "\n\n"
        if failed_count > 0:
            result_text += f"⚠️ {failed_count} clips failed. Check logs for details.\n\n"
        
        result_text += "Clip Results:\n" + "\n".join(results[:20])  # Show first 20
        if len(results) > 20:
            result_text += f"\n... and {len(results) - 20} more"
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Rendering Complete")
        msg_box.setText(message)
        msg_box.setDetailedText(result_text)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.exec()
    
    def on_error(self, error_msg):
        """Handle rendering error"""
        self.progress_bar.setVisible(False)
        self.status_label.setText("❌ Error occurred")
        self.render_button.setEnabled(True)
        
        QMessageBox.critical(
            self,
            "Rendering Error",
            f"An error occurred during rendering:\n\n{error_msg}"
        )


def main():
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    window = AutoCutterGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()