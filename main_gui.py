#!/usr/bin/env python3
"""
AutoCutter GUI - Main Application
Requires: PySide6
"""

import os
import sys
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QSpinBox, QProgressBar,
    QGroupBox, QMessageBox, QCheckBox, QDoubleSpinBox,
    QSlider, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import QFont

# Import our modules
from file_manager import FileManager
from renderer import FFmpegRenderer, RenderSession
from config_manager import ConfigManager


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('autocutter.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class CompactFilePicker(QWidget):
    """Compact file picker widget"""
    file_selected = Signal(str)
    
    def __init__(self, label_text, file_filter, parent=None):
        super().__init__(parent)
        self.file_path = None
        self.duration = 0
        self.file_filter = file_filter
        self.label_text = label_text
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Title
        title = QLabel(label_text)
        title.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(title)
        
        # File display
        self.path_label = QLabel("No file")
        self.path_label.setStyleSheet(
            "color: #666; padding: 8px; background: #f5f5f5; "
            "border: 1px solid #ddd; border-radius: 4px; font-size: 10px;"
        )
        self.path_label.setWordWrap(True)
        self.path_label.setMaximumHeight(50)
        layout.addWidget(self.path_label)
        
        # Duration
        self.duration_label = QLabel("--")
        self.duration_label.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(self.duration_label)
        
        # Browse button
        self.browse_btn = QPushButton("📁 Browse")
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background: #2196F3;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #1976D2;
            }
        """)
        self.browse_btn.clicked.connect(self.pick_file)
        layout.addWidget(self.browse_btn)
    
    def pick_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, f"Select {self.label_text}", "", self.file_filter
        )
        if file_path:
            self.set_file(file_path)
            self.file_selected.emit(file_path)
    
    def set_file(self, file_path):
        self.file_path = file_path
        filename = os.path.basename(file_path)
        self.path_label.setText(filename)
        self.path_label.setToolTip(file_path)
        self.path_label.setStyleSheet(
            "color: #2e7d32; padding: 8px; background: #e8f5e9; "
            "border: 1px solid #4caf50; border-radius: 4px; font-size: 10px;"
        )
        
        # Get duration
        self.duration = FileManager.get_media_duration(file_path)
        if self.duration > 0:
            self.duration_label.setText(
                f"Duration: {FileManager.format_duration(self.duration)} "
                f"({self.duration:.1f}s)"
            )
        else:
            self.duration_label.setText("Duration: Unknown")


class MusicPlayerWidget(QWidget):
    """Music player with timeline"""
    position_changed = Signal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.music_duration = 0
        self.is_playing = False
        self.slider_pressed = False
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Media player
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.5)
        
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        
        # Timeline
        timeline_layout = QHBoxLayout()
        timeline_layout.addWidget(QLabel("Timeline:"))
        
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setRange(0, 1000)
        self.timeline_slider.setValue(0)
        self.timeline_slider.sliderPressed.connect(lambda: setattr(self, 'slider_pressed', True))
        self.timeline_slider.sliderReleased.connect(self.on_slider_released)
        self.timeline_slider.sliderMoved.connect(self.on_slider_moved)
        timeline_layout.addWidget(self.timeline_slider, stretch=1)
        layout.addLayout(timeline_layout)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet("font-size: 11px;")
        controls_layout.addWidget(self.time_label)
        
        controls_layout.addStretch()
        
        self.play_button = QPushButton("▶")
        self.play_button.setFixedSize(60, 30)
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover { background: #45a049; }
            QPushButton:disabled { background: #ccc; }
        """)
        controls_layout.addWidget(self.play_button)
        
        self.stop_button = QPushButton("⏹")
        self.stop_button.setFixedSize(60, 30)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover { background: #da190b; }
            QPushButton:disabled { background: #ccc; }
        """)
        controls_layout.addWidget(self.stop_button)
        
        self.set_start_button = QPushButton("📍 Set Start")
        self.set_start_button.setFixedSize(100, 30)
        self.set_start_button.setEnabled(False)
        self.set_start_button.clicked.connect(self.set_start_position)
        self.set_start_button.setStyleSheet("""
            QPushButton {
                background: #FF9800;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background: #F57C00; }
            QPushButton:disabled { background: #ccc; }
        """)
        controls_layout.addWidget(self.set_start_button)
        
        layout.addLayout(controls_layout)
    
    def load_music(self, file_path):
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.set_start_button.setEnabled(True)
    
    def toggle_play(self):
        if self.is_playing:
            self.player.pause()
            self.play_button.setText("▶")
            self.is_playing = False
        else:
            self.player.play()
            self.play_button.setText("⏸")
            self.is_playing = True
    
    def stop(self):
        self.player.stop()
        self.play_button.setText("▶")
        self.is_playing = False
        self.timeline_slider.setValue(0)
    
    def on_position_changed(self, position):
        if not self.slider_pressed and self.music_duration > 0:
            value = int((position / self.music_duration) * 1000)
            self.timeline_slider.setValue(value)
        
        current = position / 1000.0
        total = self.music_duration / 1000.0
        self.time_label.setText(
            f"{int(current//60)}:{int(current%60):02d} / "
            f"{int(total//60)}:{int(total%60):02d}"
        )
    
    def on_duration_changed(self, duration):
        self.music_duration = duration
    
    def on_slider_moved(self, value):
        if self.music_duration > 0:
            position = (value / 1000.0) * self.music_duration
            current = position / 1000.0
            total = self.music_duration / 1000.0
            self.time_label.setText(
                f"{int(current//60)}:{int(current%60):02d} / "
                f"{int(total//60)}:{int(total%60):02d}"
            )
    
    def on_slider_released(self):
        self.slider_pressed = False
        if self.music_duration > 0:
            position = int((self.timeline_slider.value() / 1000.0) * self.music_duration)
            self.player.setPosition(position)
    
    def set_start_position(self):
        if self.music_duration > 0:
            current_pos = (self.timeline_slider.value() / 1000.0) * (self.music_duration / 1000.0)
            self.position_changed.emit(current_pos)
    
    def get_current_position(self):
        if self.music_duration > 0:
            return (self.timeline_slider.value() / 1000.0) * (self.music_duration / 1000.0)
        return 0


class RenderWorker(QThread):
    """Background rendering thread"""
    progress = Signal(int, str)
    finished = Signal(str, list)
    error = Signal(str)
    
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
    
    def run(self):
        try:
            # Create session
            session = RenderSession(self.settings['output_dir'])
            
            # Build tasks
            tasks = []
            num_clips = self.settings['num_clips']
            clip_length = self.settings['clip_length']
            
            for i in range(num_clips):
                output_path = session.generate_clip_filename(i, clip_length)
                tasks.append((
                    i,
                    clip_length,
                    self.settings['animation_video'],
                    self.settings['background_video'],
                    self.settings['music_file'],
                    self.settings['music_start'],
                    output_path,
                    self.settings['codec'],
                    self.settings['normalize_audio'],
                    session.log_dir,
                ))
            
            # Render in parallel
            results = []
            completed = 0
            workers = self.settings['workers']
            
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        FFmpegRenderer.render_clip,
                        *task
                    ): task for task in tasks
                }
                
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
            session.write_summary(self.settings, results)
            
            success_count = sum(1 for r in results if r.startswith("✅"))
            final_msg = (
                f"Completed: {success_count}/{len(tasks)} clips rendered successfully!\n\n"
                f"Output folder: {session.session_dir}"
            )
            
            self.finished.emit(final_msg, results)
            
        except Exception as e:
            logger.error(f"Rendering error: {e}", exc_info=True)
            self.error.emit(str(e))


class AutoCutterGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoCutter - Professional Video Clip Generator")
        self.resize(1000, 700)
        
        # Load config
        self.config = ConfigManager()
        
        # Check FFmpeg
        if not FileManager.check_ffmpeg_available():
            QMessageBox.critical(
                self,
                "FFmpeg Not Found",
                "FFmpeg and FFprobe are required but not found.\n\n"
                "Download: https://ffmpeg.org/download.html"
            )
            sys.exit(1)
        
        self.setup_ui()
        self.load_settings_from_config()
        
        logger.info("AutoCutter GUI started")
    
    def setup_ui(self):
        """Setup the user interface"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Header
        header = QLabel("🎬 AutoCutter")
        header.setFont(QFont("Arial", 24, QFont.Bold))
        header.setStyleSheet("color: #1976D2; padding: 10px;")
        header.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header)
        
        subtitle = QLabel("Professional Video Clip Generator")
        subtitle.setStyleSheet("color: #666; font-size: 13px;")
        subtitle.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(subtitle)
        
        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line)
        
        # === FILE INPUTS (HORIZONTAL) ===
        files_group = QGroupBox("📁 Input Files")
        files_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        files_layout = QHBoxLayout()
        files_layout.setSpacing(10)
        
        self.bg_picker = CompactFilePicker(
            "Background Video",
            "Videos (*.mp4 *.mov *.mkv *.avi *.webm)"
        )
        self.bg_picker.file_selected.connect(self.on_background_changed)
        files_layout.addWidget(self.bg_picker)
        
        self.anim_picker = CompactFilePicker(
            "Animation/Overlay",
            "Videos (*.mov *.mp4 *.mkv *.webm)"
        )
        self.anim_picker.file_selected.connect(self.on_animation_changed)
        files_layout.addWidget(self.anim_picker)
        
        self.music_picker = CompactFilePicker(
            "Music/Audio",
            "Audio (*.mp3 *.wav *.aac *.m4a *.ogg)"
        )
        self.music_picker.file_selected.connect(self.on_music_changed)
        files_layout.addWidget(self.music_picker)
        
        files_group.setLayout(files_layout)
        main_layout.addWidget(files_group)
        
        # === SETTINGS ===
        settings_group = QGroupBox("⚙️ Clip Configuration")
        settings_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(10)
        
        # Row 1: Clip length and max clips
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Clip Length (seconds):"))
        self.clip_length_spin = QSpinBox()
        self.clip_length_spin.setRange(1, 60)
        self.clip_length_spin.setValue(10)
        self.clip_length_spin.setFixedWidth(80)
        self.clip_length_spin.valueChanged.connect(self.update_calculations)
        row1.addWidget(self.clip_length_spin)
        
        row1.addSpacing(20)
        self.max_clips_label = QLabel("Max clips: --")
        self.max_clips_label.setStyleSheet("color: #1976D2; font-weight: bold;")
        row1.addWidget(self.max_clips_label)
        row1.addStretch()
        settings_layout.addLayout(row1)
        
        # Row 2: Number of clips
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Number of clips to generate:"))
        self.num_clips_spin = QSpinBox()
        self.num_clips_spin.setRange(1, 1000)
        self.num_clips_spin.setValue(1)
        self.num_clips_spin.setFixedWidth(80)
        row2.addWidget(self.num_clips_spin)
        row2.addStretch()
        settings_layout.addLayout(row2)
        
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)
        
        # === MUSIC ===
        music_group = QGroupBox("🎵 Music Selection")
        music_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        music_layout = QVBoxLayout()
        music_layout.setSpacing(8)
        
        info_label = QLabel("Play and set music start position:")
        info_label.setStyleSheet("font-style: italic; color: #666;")
        music_layout.addWidget(info_label)
        
        self.music_player = MusicPlayerWidget()
        self.music_player.position_changed.connect(self.on_music_position_set)
        music_layout.addWidget(self.music_player)
        
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("Start time:"))
        self.music_start_spin = QDoubleSpinBox()
        self.music_start_spin.setRange(0, 10000)
        self.music_start_spin.setValue(0)
        self.music_start_spin.setDecimals(1)
        self.music_start_spin.setSingleStep(0.5)
        self.music_start_spin.setFixedWidth(80)
        self.music_start_spin.valueChanged.connect(self.update_music_end)
        start_layout.addWidget(self.music_start_spin)
        start_layout.addWidget(QLabel("seconds"))
        
        start_layout.addSpacing(20)
        self.music_end_label = QLabel("End: 10.0s")
        self.music_end_label.setStyleSheet("color: #4CAF50;")
        start_layout.addWidget(self.music_end_label)
        start_layout.addStretch()
        music_layout.addLayout(start_layout)
        
        music_group.setLayout(music_layout)
        main_layout.addWidget(music_group)
        
        # === ADVANCED ===
        advanced_group = QGroupBox("🔧 Advanced Options")
        advanced_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        advanced_layout = QHBoxLayout()
        
        self.gpu_checkbox = QCheckBox("GPU Encoding (NVENC)")
        advanced_layout.addWidget(self.gpu_checkbox)
        
        self.normalize_checkbox = QCheckBox("Audio Normalization")
        self.normalize_checkbox.setChecked(True)
        advanced_layout.addWidget(self.normalize_checkbox)
        
        advanced_layout.addSpacing(20)
        advanced_layout.addWidget(QLabel("Workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, os.cpu_count() or 4)
        self.workers_spin.setValue(max(1, (os.cpu_count() or 2) // 2))
        self.workers_spin.setFixedWidth(60)
        advanced_layout.addWidget(self.workers_spin)
        
        advanced_layout.addStretch()
        advanced_group.setLayout(advanced_layout)
        main_layout.addWidget(advanced_group)
        
        # === PROGRESS ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #ddd;
                border-radius: 5px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
        """)
        main_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-weight: bold; color: #1976D2;")
        main_layout.addWidget(self.status_label)
        
        # === RENDER BUTTON ===
        self.render_button = QPushButton("🚀 START RENDERING")
        self.render_button.setMinimumHeight(60)
        self.render_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.render_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4CAF50, stop:1 #45a049);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 15px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #45a049, stop:1 #3d8b40);
            }
            QPushButton:pressed {
                background: #2e7d32;
            }
            QPushButton:disabled {
                background: #cccccc;
                color: #666666;
            }
        """)
        self.render_button.clicked.connect(self.start_rendering)
        main_layout.addWidget(self.render_button)
        
        main_layout.addStretch()
    
    def load_settings_from_config(self):
        """Load settings from config"""
        self.clip_length_spin.setValue(self.config.get('default_clip_length', 10))
        self.workers_spin.setValue(self.config.get('default_workers', 2))
        self.gpu_checkbox.setChecked(self.config.get('prefer_gpu', False))
        self.normalize_checkbox.setChecked(self.config.get('use_audio_normalization', True))
    
    def save_settings_to_config(self):
        """Save current settings to config"""
        self.config.set('default_clip_length', self.clip_length_spin.value())
        self.config.set('default_workers', self.workers_spin.value())
        self.config.set('prefer_gpu', self.gpu_checkbox.isChecked())
        self.config.set('use_audio_normalization', self.normalize_checkbox.isChecked())
        self.config.save_config()
    
    def on_background_changed(self, file_path):
        self.config.add_recent_file('backgrounds', file_path)
        self.update_calculations()
    
    def on_animation_changed(self, file_path):
        self.config.add_recent_file('animations', file_path)
        if self.anim_picker.duration > 0:
            max_duration = int(self.anim_picker.duration)
            self.clip_length_spin.setMaximum(max_duration)
            if self.clip_length_spin.value() > max_duration:
                self.clip_length_spin.setValue(max_duration)
        self.update_calculations()
    
    def on_music_changed(self, file_path):
        self.config.add_recent_file('music', file_path)
        self.music_player.load_music(file_path)
        self.update_music_end()
    
    def on_music_position_set(self, position):
        self.music_start_spin.setValue(position)
        QMessageBox.information(
            self,
            "Position Set",
            f"Music start: {position:.1f}s"
        )
    
    def update_calculations(self):
        bg_dur = self.bg_picker.duration
        clip_len = self.clip_length_spin.value()
        
        if bg_dur > 0 and clip_len > 0:
            max_clips = int(bg_dur // clip_len)
            self.max_clips_label.setText(f"Max clips: {max_clips}")
            self.num_clips_spin.setMaximum(max(1, max_clips))
            if self.num_clips_spin.value() > max_clips:
                self.num_clips_spin.setValue(max(1, max_clips))
        else:
            self.max_clips_label.setText("Max clips: --")
        
        self.update_music_end()
    
    def update_music_end(self):
        start = self.music_start_spin.value()
        duration = self.clip_length_spin.value()
        end = start + duration
        
        self.music_end_label.setText(f"End: {end:.1f}s (Duration: {duration}s)")
        
        if self.music_picker.duration > 0 and end > self.music_picker.duration:
            self.music_end_label.setStyleSheet("color: #f44336; font-weight: bold;")
            self.music_end_label.setText(f"End: {end:.1f}s ⚠️ EXCEEDS music!")
        else:
            self.music_end_label.setStyleSheet("color: #4CAF50;")
    
    def validate_inputs(self):
        errors = []
        
        if not self.bg_picker.file_path:
            errors.append("❌ No background video selected")
        if not self.anim_picker.file_path:
            errors.append("❌ No animation video selected")
        if not self.music_picker.file_path:
            errors.append("❌ No music file selected")
        
        if self.anim_picker.duration > 0:
            if self.clip_length_spin.value() > self.anim_picker.duration:
                errors.append(f"❌ Clip length exceeds animation duration")
        
        music_end = self.music_start_spin.value() + self.clip_length_spin.value()
        if self.music_picker.duration > 0 and music_end > self.music_picker.duration:
            errors.append(f"❌ Music segment exceeds music duration")
        
        return errors
    
    def start_rendering(self):
        errors = self.validate_inputs()
        
        if errors:
            QMessageBox.warning(
                self,
                "Validation Errors",
                "\n".join(errors)
            )
            return
        
        # Get codec
        codec = FFmpegRenderer.get_best_codec(self.gpu_checkbox.isChecked())
        
        # Prepare settings
        settings = {
            'background_video': self.bg_picker.file_path,
            'animation_video': self.anim_picker.file_path,
            'music_file': self.music_picker.file_path,
            'clip_length': self.clip_length_spin.value(),
            'num_clips': self.num_clips_spin.value(),
            'music_start': self.music_start_spin.value(),
            'codec': codec,
            'normalize_audio': self.normalize_checkbox.isChecked(),
            'workers': self.workers_spin.value(),
            'output_dir': self.config.get('last_output_dir', './output')
        }
        
        # Confirm
        reply = QMessageBox.question(
            self,
            "Confirm Rendering",
            f"Ready to render {settings['num_clips']} clips?\n\n"
            f"Clip length: {settings['clip_length']}s\n"
            f"Codec: {codec}\n"
            f"Workers: {settings['workers']}",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.execute_render(settings)
    
    def execute_render(self, settings):
        self.music_player.stop()
        self.render_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("🔄 Initializing...")
        
        self.worker = RenderWorker(settings)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()
        
        logger.info("Rendering started")
    
    def on_progress(self, value, clip_name):
        self.progress_bar.setValue(value)
        self.status_label.setText(f"🔄 {clip_name}")
    
    def on_finished(self, message, results):
        self.progress_bar.setVisible(False)
        self.status_label.setText("✅ Complete!")
        self.render_button.setEnabled(True)
        
        self.save_settings_to_config()
        
        QMessageBox.information(self, "Rendering Complete", message)
        logger.info("Rendering completed successfully")
    
    def on_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.status_label.setText("❌ Error")
        self.render_button.setEnabled(True)
        
        QMessageBox.critical(self, "Error", f"Rendering failed:\n\n{error_msg}")
        logger.error(f"Rendering error: {error_msg}")
    
    def closeEvent(self, event):
        """Save config on close"""
        self.save_settings_to_config()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = AutoCutterGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()