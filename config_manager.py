#!/usr/bin/env python3
"""
Configuration Manager - Handles settings persistence
"""

import json
import os
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages application configuration and settings persistence"""
    
    DEFAULT_CONFIG = {
        "last_background_dir": "",
        "last_animation_dir": "",
        "last_music_dir": "",
        "last_output_dir": "./output",
        "default_clip_length": 10,
        "default_workers": 2,
        "prefer_gpu": False,
        "use_audio_normalization": True,
        "recent_files": {
            "backgrounds": [],
            "animations": [],
            "music": []
        }
    }
    
    def __init__(self, config_file="autocutter_config.json"):
        """
        Initialize configuration manager
        
        Args:
            config_file: Path to configuration file
        """
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self):
        """
        Load configuration from file
        
        Returns:
            dict: Configuration dictionary
        """
        if not os.path.exists(self.config_file):
            logger.info("Config file not found, using defaults")
            return self.DEFAULT_CONFIG.copy()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                
            # Merge with defaults (in case new keys were added)
            config = self.DEFAULT_CONFIG.copy()
            config.update(loaded)
            
            logger.info(f"Loaded config from {self.config_file}")
            return config
            
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return self.DEFAULT_CONFIG.copy()
    
    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved config to {self.config_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            return False
    
    def get(self, key, default=None):
        """
        Get configuration value
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        return self.config.get(key, default)
    
    def set(self, key, value):
        """
        Set configuration value
        
        Args:
            key: Configuration key
            value: Value to set
        """
        self.config[key] = value
    
    def add_recent_file(self, file_type, file_path):
        """
        Add file to recent files list
        
        Args:
            file_type: Type of file ('backgrounds', 'animations', 'music')
            file_path: Path to file
        """
        if file_type not in self.config["recent_files"]:
            return
        
        recent = self.config["recent_files"][file_type]
        
        # Remove if already exists
        if file_path in recent:
            recent.remove(file_path)
        
        # Add to front
        recent.insert(0, file_path)
        
        # Keep only last 10
        self.config["recent_files"][file_type] = recent[:10]
    
    def get_recent_files(self, file_type):
        """
        Get recent files of specific type
        
        Args:
            file_type: Type of file ('backgrounds', 'animations', 'music')
            
        Returns:
            list: List of recent file paths
        """
        recent = self.config["recent_files"].get(file_type, [])
        # Filter out files that no longer exist
        return [f for f in recent if os.path.exists(f)]
    
    def update_last_directory(self, file_type, directory):
        """
        Update last used directory for file type
        
        Args:
            file_type: Type of file ('background', 'animation', 'music', 'output')
            directory: Directory path
        """
        key = f"last_{file_type}_dir"
        self.config[key] = directory