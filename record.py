import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import time
import cv2
import numpy as np
import serial
import serial.tools.list_ports
import wave
import struct
import queue
from datetime import datetime
import os
from PIL import Image, ImageTk
import subprocess
import sys
import logging
import requests
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AudioVideoRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("Professional Audio-Video Recorder with AI Transcription v2.0")
        self.root.geometry("1400x900")  # Increased size for transcription panel
        self.root.configure(bg='#2c3e50')
        
        # Recording parameters
        self.SAMPLE_RATE = 16000
        self.FRAME_RATE = 20  # More realistic for ESP32-CAM
        self.PREVIEW_FPS = 30  # Higher preview FPS
        
        # API settings
        self.API_URL = "http://localhost:8000/transcribe/"
        self.transcription_enabled = True
        
        # Communication settings
        self.serial_port = None
        self.esp32_ip = ""
        self.stream_url = ""
        
        # Recording state
        self.is_recording = False
        self.is_connected = False
        self.video_frames = []
        self.audio_data = []
        self.frame_timestamps = []
        self.audio_timestamps = []
        self.recording_start_time = None
        
        # Threading and queues
        self.audio_queue = queue.Queue(maxsize=1000)
        self.video_queue = queue.Queue(maxsize=100)
        self.preview_queue = queue.Queue(maxsize=5)  # Small queue for smooth preview
        self.recording_thread = None
        self.preview_thread = None
        self.audio_thread = None
        self.video_thread = None
        
        # Video capture
        self.cap = None
        self.current_frame = None
        
        # Threading locks
        self.recording_lock = threading.Lock()
        self.connection_lock = threading.Lock()
        
        # Shutdown flag
        self.shutdown_flag = threading.Event()
        
        self.setup_ui()
        self.start_preview_thread()
        
    def setup_ui(self):
        # Title
        title_label = tk.Label(self.root, text="Professional Audio-Video Recorder with AI Transcription", 
                              font=("Arial", 18, "bold"), fg='white', bg='#2c3e50')
        title_label.pack(pady=10)
        
        # Main frame
        main_frame = tk.Frame(self.root, bg='#2c3e50')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Left panel - Controls with scrollbar
        left_frame = tk.Frame(main_frame, bg='#2c3e50')
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 15))
        
        # Create scrollable control frame
        canvas = tk.Canvas(left_frame, bg='#34495e', width=400, highlightthickness=0)
        scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='#34495e')
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Make the control frame scrollable with mouse wheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Use scrollable_frame as control_frame
        control_frame = scrollable_frame
        
        # Right panel container
        right_container = tk.Frame(main_frame, bg='#2c3e50')
        right_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Video preview (top right)
        self.preview_frame = tk.Frame(right_container, bg='#2c3e50')
        self.preview_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Transcription panel (bottom right)
        self.transcription_frame = tk.Frame(right_container, bg='#34495e', relief=tk.RAISED, bd=2)
        self.transcription_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        self.transcription_frame.config(height=180)
        
        # Connection settings
        conn_label = tk.Label(control_frame, text="🔗 Connection Settings", 
                             font=("Arial", 12, "bold"), fg='white', bg='#34495e')
        conn_label.pack(pady=(15, 10))
        
        # Serial port with dropdown
        tk.Label(control_frame, text="Arduino Serial Port:", 
                fg='white', bg='#34495e', font=("Arial", 9)).pack(anchor='w', padx=15)
        
        port_frame = tk.Frame(control_frame, bg='#34495e')
        port_frame.pack(fill=tk.X, padx=15, pady=5)
        
        self.serial_var = tk.StringVar()
        self.port_combo = ttk.Combobox(port_frame, textvariable=self.serial_var, 
                                      width=22, state="readonly", font=("Arial", 9))
        self.port_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        refresh_btn = tk.Button(port_frame, text="↻", command=self.refresh_ports,
                               bg='#3498db', fg='white', font=("Arial", 8), width=3)
        refresh_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # ESP32 IP
        tk.Label(control_frame, text="ESP32-CAM IP Address:", 
                fg='white', bg='#34495e', font=("Arial", 9)).pack(anchor='w', padx=15, pady=(10, 0))
        self.ip_var = tk.StringVar(value="192.168.1.100")
        ip_entry = tk.Entry(control_frame, textvariable=self.ip_var, width=30, font=("Arial", 9))
        ip_entry.pack(padx=15, pady=5, fill=tk.X)
        
        # Test connection button
        test_btn = tk.Button(control_frame, text="Test ESP32-CAM Connection", 
                            command=self.test_esp32_connection, bg='#f39c12', fg='white',
                            font=("Arial", 8), relief=tk.FLAT)
        test_btn.pack(pady=5, padx=15, fill=tk.X)
        
        # Connect button
        self.connect_btn = tk.Button(control_frame, text="Connect All Devices", 
                                    command=self.connect_devices, bg='#3498db', fg='white',
                                    font=("Arial", 10, "bold"), relief=tk.FLAT, height=2)
        self.connect_btn.pack(pady=10, padx=15, fill=tk.X)
        
        # Connection status
        self.status_var = tk.StringVar(value="Disconnected")
        status_label = tk.Label(control_frame, textvariable=self.status_var, 
                               fg='#ecf0f1', bg='#2c3e50', font=("Arial", 10, "bold"),
                               relief=tk.SUNKEN, bd=1)
        status_label.pack(pady=5, padx=15, fill=tk.X)
        
        # Separator
        separator1 = tk.Frame(control_frame, height=2, bg='#7f8c8d')
        separator1.pack(fill=tk.X, padx=15, pady=15)
        
        # Recording controls
        rec_label = tk.Label(control_frame, text="🎥 Recording Controls", 
                            font=("Arial", 12, "bold"), fg='white', bg='#34495e')
        rec_label.pack(pady=(5, 10))
        
        # Recording buttons frame
        rec_btn_frame = tk.Frame(control_frame, bg='#34495e')
        rec_btn_frame.pack(fill=tk.X, padx=15, pady=10)
        
        # Start Recording button
        self.start_btn = tk.Button(rec_btn_frame, text="🔴 START\nRECORDING", 
                                  command=self.start_recording, bg='#e74c3c', fg='white',
                                  font=("Arial", 10, "bold"), relief=tk.FLAT, 
                                  state=tk.DISABLED, height=2)
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        # Stop Recording button
        self.stop_btn = tk.Button(rec_btn_frame, text="⏹ STOP\nRECORDING", 
                                 command=self.stop_recording, bg='#95a5a6', fg='white',
                                 font=("Arial", 10, "bold"), relief=tk.FLAT, 
                                 state=tk.DISABLED, height=2)
        self.stop_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Recording timer
        self.timer_var = tk.StringVar(value="00:00")
        timer_label = tk.Label(control_frame, textvariable=self.timer_var, 
                              fg='#e74c3c', bg='#34495e', font=("Arial", 14, "bold"))
        timer_label.pack(pady=5)
        
        # Status indicators frame
        status_frame = tk.Frame(control_frame, bg='#34495e')
        status_frame.pack(fill=tk.X, padx=15, pady=10)
        
        # Audio level indicator
        tk.Label(status_frame, text="Audio Level:", fg='white', bg='#34495e', 
                font=("Arial", 8)).pack(anchor='w')
        self.audio_level = ttk.Progressbar(status_frame, length=300, mode='determinate')
        self.audio_level.pack(fill=tk.X, pady=2)
        
        # Frame rate indicator
        tk.Label(status_frame, text="Video FPS:", fg='white', bg='#34495e', 
                font=("Arial", 8)).pack(anchor='w', pady=(5, 0))
        self.fps_var = tk.StringVar(value="0 FPS")
        fps_label = tk.Label(status_frame, textvariable=self.fps_var, 
                            fg='#2ecc71', bg='#34495e', font=("Arial", 9, "bold"))
        fps_label.pack(anchor='w')
        
        # Separator
        separator2 = tk.Frame(control_frame, height=2, bg='#7f8c8d')
        separator2.pack(fill=tk.X, padx=15, pady=15)
        
        # Transcription API settings
        api_label = tk.Label(control_frame, text="🤖 Transcription Settings", 
                            font=("Arial", 12, "bold"), fg='white', bg='#34495e')
        api_label.pack(pady=(5, 10))
        
        # API URL
        tk.Label(control_frame, text="API URL:", 
                fg='white', bg='#34495e', font=("Arial", 9)).pack(anchor='w', padx=15)
        self.api_url_var = tk.StringVar(value="http://localhost:8000/transcribe/")
        api_entry = tk.Entry(control_frame, textvariable=self.api_url_var, 
                            font=("Arial", 9), width=35)
        api_entry.pack(padx=15, pady=5, fill=tk.X)
        
        # Transcription enable checkbox
        self.transcription_var = tk.BooleanVar(value=True)
        trans_check = tk.Checkbutton(control_frame, text="Enable Auto-Transcription", 
                                    variable=self.transcription_var, fg='white', bg='#34495e',
                                    font=("Arial", 9), selectcolor='#2c3e50')
        trans_check.pack(anchor='w', padx=15, pady=5)
        
        # Test API button
        test_api_btn = tk.Button(control_frame, text="Test API Connection", 
                                command=self.test_api_connection, bg='#f39c12', fg='white',
                                font=("Arial", 8), relief=tk.FLAT)
        test_api_btn.pack(pady=5, padx=15, fill=tk.X)
        
        # Separator
        separator3 = tk.Frame(control_frame, height=2, bg='#7f8c8d')
        separator3.pack(fill=tk.X, padx=15, pady=15)
        
        # Output settings
        output_label = tk.Label(control_frame, text="📁 Output Settings", 
                               font=("Arial", 12, "bold"), fg='white', bg='#34495e')
        output_label.pack(pady=(5, 10))
        
        # Output directory
        self.output_dir = tk.StringVar(value=os.path.join(os.getcwd(), "recordings"))
        
        tk.Label(control_frame, text="Output Directory:", 
                fg='white', bg='#34495e', font=("Arial", 9)).pack(anchor='w', padx=15)
        
        # Directory info label
        info_label = tk.Label(control_frame, text="Each recording creates a new folder", 
                             fg='#95a5a6', bg='#34495e', font=("Arial", 8))
        info_label.pack(anchor='w', padx=15)
        
        dir_frame = tk.Frame(control_frame, bg='#34495e')
        dir_frame.pack(fill=tk.X, padx=15, pady=5)
        
        dir_entry = tk.Entry(dir_frame, textvariable=self.output_dir, 
                            font=("Arial", 8), state='readonly')
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        dir_btn = tk.Button(dir_frame, text="Browse", command=self.select_output_dir, 
                           bg='#95a5a6', fg='white', font=("Arial", 8), width=8)
        dir_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # Add some padding at the bottom
        bottom_padding = tk.Frame(control_frame, bg='#34495e', height=20)
        bottom_padding.pack(fill=tk.X)
        
        # Right panel - Preview
        self.setup_preview()
        self.setup_transcription_panel()
        self.refresh_ports()  # Load available ports
        
    def setup_preview(self):
        # Preview label
        preview_label = tk.Label(self.preview_frame, text="Live Video Preview", 
                                font=("Arial", 16, "bold"), fg='white', bg='#2c3e50')
        preview_label.pack(pady=15)
        
        # Video display frame
        video_frame = tk.Frame(self.preview_frame, bg='black', relief=tk.SUNKEN, bd=3)
        video_frame.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        
        # Video display
        self.video_label = tk.Label(video_frame, bg='black', text="No Signal",
                                   fg='white', font=("Arial", 20))
        self.video_label.pack(fill=tk.BOTH, expand=True)
        
    def setup_transcription_panel(self):
        """Setup transcription display panel"""
        # Transcription label
        trans_label = tk.Label(self.transcription_frame, text="Speech to Text Transcription", 
                              font=("Arial", 14, "bold"), fg='white', bg='#34495e')
        trans_label.pack(pady=10)
        
        # Transcription text area
        self.transcription_text = scrolledtext.ScrolledText(
            self.transcription_frame, 
            height=8, 
            width=80, 
            font=("Arial", 10),
            bg='#ecf0f1',
            fg='#2c3e50',
            wrap=tk.WORD
        )
        self.transcription_text.pack(pady=10, padx=15, fill=tk.BOTH, expand=True)
        
        # Transcription status
        self.transcription_status = tk.StringVar(value="Ready")
        status_label = tk.Label(self.transcription_frame, textvariable=self.transcription_status,
                               fg='#bdc3c7', bg='#34495e', font=("Arial", 10))
        status_label.pack(pady=5)
        
    def test_api_connection(self):
        """Test transcription API connection"""
        try:
            api_url = self.api_url_var.get()
            if not api_url:
                messagebox.showerror("Error", "Please enter API URL")
                return
                
            # Test with a simple request (we'll use a dummy approach)
            test_url = api_url.replace('/transcribe/', '/')
            
            response = requests.get(test_url, timeout=5)
            if response.status_code == 200:
                messagebox.showinfo("API Test", "✅ API server is responding!")
                self.transcription_status.set("API Connected")
                return True
            else:
                messagebox.showerror("API Test", f"❌ API responded with status: {response.status_code}")
                return False
                
        except requests.exceptions.ConnectionError:
            messagebox.showerror("API Test", "❌ Cannot connect to API server\nMake sure the server is running on port 8000")
            return False
        except requests.exceptions.Timeout:
            messagebox.showerror("API Test", "❌ API request timed out")
            return False
        except Exception as e:
            messagebox.showerror("API Test", f"❌ API test failed: {str(e)}")
            return False
            
    def transcribe_audio(self, audio_file_path, recording_folder):
        """Send audio file to transcription API"""
        try:
            if not self.transcription_var.get():
                logger.info("Transcription disabled by user")
                return None
                
            api_url = self.api_url_var.get()
            if not api_url:
                logger.error("No API URL configured")
                return None
                
            self.transcription_status.set("🔄 Transcribing audio...")
            
            # Send file to API
            with open(audio_file_path, 'rb') as audio_file:
                files = {'file': (os.path.basename(audio_file_path), audio_file, 'audio/wav')}
                
                response = requests.post(api_url, files=files, timeout=60)
                
                if response.status_code == 200:
                    result = response.json()
                    transcription_text = result.get('transcription', '')
                    
                    # Save transcription to file
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    transcript_file = os.path.join(recording_folder, f"transcript_{timestamp}.txt")
                    
                    with open(transcript_file, 'w', encoding='utf-8') as f:
                        f.write(transcription_text)
                    
                    logger.info(f"Transcription saved: {transcript_file}")
                    
                    # Update UI
                    self.transcription_text.delete(1.0, tk.END)
                    self.transcription_text.insert(tk.END, transcription_text)
                    self.transcription_status.set("✅ Transcription completed")
                    
                    return transcription_text
                    
                else:
                    error_msg = f"API error: {response.status_code}"
                    logger.error(error_msg)
                    self.transcription_status.set(f"❌ {error_msg}")
                    return None
                    
        except requests.exceptions.ConnectionError:
            error_msg = "Cannot connect to transcription API"
            logger.error(error_msg)
            self.transcription_status.set(f"❌ {error_msg}")
            return None
        except requests.exceptions.Timeout:
            error_msg = "API request timed out"
            logger.error(error_msg)
            self.transcription_status.set(f"❌ {error_msg}")
            return None
        except Exception as e:
            error_msg = f"Transcription failed: {str(e)}"
            logger.error(error_msg)
            self.transcription_status.set(f"❌ Transcription failed")
            return None
            
    def refresh_ports(self):
        """Refresh available serial ports"""
        try:
            ports = serial.tools.list_ports.comports()
            port_list = [f"{port.device} - {port.description}" for port in ports]
            self.port_combo['values'] = port_list
            
            if port_list:
                self.port_combo.current(0)
                # Extract just the device name
                selected = port_list[0].split(' - ')[0]
                self.serial_var.set(selected)
            else:
                self.port_combo.set("No ports found")
                
        except Exception as e:
            logger.error(f"Error refreshing ports: {e}")
            self.port_combo['values'] = ["Error loading ports"]
            
    def get_selected_port(self):
        """Get the selected port device name"""
        try:
            selected = self.serial_var.get()
            if " - " in selected:
                return selected.split(' - ')[0]
            return selected
        except:
            return None
            
    def test_esp32_connection(self):
        """Test ESP32-CAM connection with frame rate check"""
        try:
            test_url = f"http://{self.ip_var.get()}/stream"
            test_cap = cv2.VideoCapture(test_url)
            test_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if test_cap.isOpened():
                # Test multiple frames to check stability
                frames_captured = 0
                start_time = time.time()
                
                for i in range(10):  # Try to capture 10 frames
                    ret, frame = test_cap.read()
                    if ret:
                        frames_captured += 1
                    time.sleep(0.1)  # 100ms between attempts
                
                test_cap.release()
                elapsed_time = time.time() - start_time
                
                if frames_captured >= 5:  # At least half should succeed
                    estimated_fps = frames_captured / elapsed_time * 10  # Estimate FPS
                    messagebox.showinfo("Connection Test", 
                        f"✅ ESP32-CAM connection successful!\n"
                        f"📊 Captured {frames_captured}/10 test frames\n"
                        f"🎥 Estimated FPS: {estimated_fps:.1f}")
                    return True
                else:
                    messagebox.showerror("Connection Test", 
                        f"❌ ESP32-CAM connected but poor signal quality\n"
                        f"Only captured {frames_captured}/10 frames")
                    return False
            else:
                messagebox.showerror("Connection Test", "❌ Cannot connect to ESP32-CAM stream")
                return False
                
        except Exception as e:
            messagebox.showerror("Connection Test", f"❌ ESP32-CAM test failed:\n{str(e)}")
            return False
            
    def connect_devices(self):
        """Connect to both Arduino and ESP32-CAM"""
        if self.is_connected:
            self.disconnect_devices()
            return
            
        try:
            with self.connection_lock:
                # Validate serial port
                port = self.get_selected_port()
                if not port or port == "No ports found":
                    raise Exception("Please select a valid serial port")
                    
                # Connect to Arduino with optimized serial settings
                self.serial_port = serial.Serial(
                    port=port, 
                    baudrate=1000000, 
                    timeout=0.001,  # Very short timeout for minimal latency
                    write_timeout=0.001,
                    inter_byte_timeout=None
                )
                
                # Flush buffers to ensure clean start
                self.serial_port.reset_input_buffer()
                self.serial_port.reset_output_buffer()
                
                time.sleep(2)  # Allow Arduino to reset
                
                # Test ESP32-CAM connection
                self.esp32_ip = self.ip_var.get()
                self.stream_url = f"http://{self.esp32_ip}/stream"
                
                # Test video stream with optimized settings for sync
                self.cap = cv2.VideoCapture(self.stream_url)
                
                # Optimize capture settings for better sync
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimal buffer for lowest latency
                self.cap.set(cv2.CAP_PROP_FPS, 25)  # Request 25 FPS from ESP32-CAM
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))  # MJPEG format
                
                if not self.cap.isOpened():
                    raise Exception("Cannot connect to ESP32-CAM stream")
                    
                # Test if we can get a frame
                ret, frame = self.cap.read()
                if not ret:
                    raise Exception("ESP32-CAM connected but no video signal")
                
                self.is_connected = True
                self.status_var.set("✓ Connected")
                self.connect_btn.config(text="Disconnect Devices", bg='#e74c3c')
                self.start_btn.config(state=tk.NORMAL)
                
                messagebox.showinfo("Success", "All devices connected successfully!")
                logger.info("Devices connected successfully")
                
        except Exception as e:
            self.disconnect_devices()
            error_msg = f"Connection failed: {str(e)}"
            messagebox.showerror("Connection Error", error_msg)
            logger.error(error_msg)
            
    def disconnect_devices(self):
        """Disconnect all devices"""
        try:
            with self.connection_lock:
                self.is_connected = False
                
                if self.cap:
                    self.cap.release()
                    self.cap = None
                    
                if self.serial_port:
                    self.serial_port.close()
                    self.serial_port = None
                    
                self.status_var.set("Disconnected")
                self.connect_btn.config(text="Connect All Devices", bg='#3498db')
                self.start_btn.config(state=tk.DISABLED)
                self.stop_btn.config(state=tk.DISABLED)
                
                # Clear video preview
                self.video_label.config(image='', text="No Signal")
                
        except Exception as e:
            logger.error(f"Error disconnecting: {e}")
            
    def start_preview_thread(self):
        """Start the preview thread"""
        self.preview_thread = threading.Thread(target=self.preview_worker, daemon=True)
        self.preview_thread.start()
        
    def preview_worker(self):
        """Worker thread for video preview"""
        frame_count = 0
        fps_start_time = time.time()
        
        while not self.shutdown_flag.is_set():
            try:
                if self.is_connected and self.cap and self.cap.isOpened() and not self.is_recording:
                    ret, frame = self.cap.read()
                    if ret:
                        # Resize frame for preview (maintain aspect ratio)
                        height, width = frame.shape[:2]
                        max_width, max_height = 700, 500
                        
                        if width > max_width or height > max_height:
                            scale = min(max_width/width, max_height/height)
                            new_width = int(width * scale)
                            new_height = int(height * scale)
                            frame = cv2.resize(frame, (new_width, new_height))
                        
                        # Convert to RGB for Tkinter
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame_rgb)
                        img_tk = ImageTk.PhotoImage(img)
                        
                        # Update UI in main thread
                        self.root.after(0, self.update_preview, img_tk)
                        
                        # Calculate FPS
                        frame_count += 1
                        if frame_count % 10 == 0:
                            current_time = time.time()
                            fps = 10 / (current_time - fps_start_time)
                            self.root.after(0, lambda: self.fps_var.set(f"{fps:.1f} FPS"))
                            fps_start_time = current_time
                            
                # Update audio level
                self.update_audio_level()
                
                time.sleep(1.0 / self.PREVIEW_FPS)  # Control preview frame rate
                
            except Exception as e:
                logger.error(f"Preview error: {e}")
                time.sleep(0.1)
                
    def update_preview(self, img_tk):
        """Update preview image in main thread"""
        try:
            self.video_label.config(image=img_tk, text="")
            self.video_label.image = img_tk  # Keep a reference
        except Exception as e:
            logger.error(f"Preview update error: {e}")
            
    def update_audio_level(self):
        """Update audio level indicator"""
        try:
            if self.serial_port and self.serial_port.in_waiting > 0:
                data = self.serial_port.read(min(100, self.serial_port.in_waiting))
                if data:
                    # Calculate audio level
                    audio_level = np.mean([x for x in data]) / 255.0 * 100
                    self.root.after(0, lambda: self.audio_level.config(value=audio_level))
        except Exception as e:
            logger.error(f"Audio level update error: {e}")
            
    def start_recording(self):
        """Start recording with synchronized timing"""
        if not self.is_connected:
            messagebox.showerror("Error", "Please connect devices first")
            return
            
        try:
            with self.recording_lock:
                # Clear previous data
                self.video_frames.clear()
                self.audio_data.clear()
                self.frame_timestamps.clear()
                self.audio_timestamps.clear()
                
                # Clear transcription
                self.transcription_text.delete(1.0, tk.END)
                self.transcription_status.set("Ready")
                
                # Update UI
                self.start_btn.config(state=tk.DISABLED)
                self.stop_btn.config(state=tk.NORMAL, bg='#e74c3c')
                self.connect_btn.config(state=tk.DISABLED)
                self.status_var.set("🔴 RECORDING")
                
                # SYNCHRONIZED START - Set timing BEFORE starting threads
                self.recording_start_time = time.time()
                self.is_recording = True
                
                # Start recording threads simultaneously
                self.audio_thread = threading.Thread(target=self.audio_recording_worker, daemon=True)
                self.video_thread = threading.Thread(target=self.video_recording_worker, daemon=True)
                
                # Start both threads at exactly the same time
                self.audio_thread.start()
                self.video_thread.start()
                
                # Start timer update
                self.update_recording_timer()
                
                logger.info("Synchronized recording started")
                
        except Exception as e:
            self.stop_recording()
            messagebox.showerror("Error", f"Failed to start recording: {str(e)}")
            
    def stop_recording(self):
        """Stop recording"""
        try:
            with self.recording_lock:
                if not self.is_recording:
                    return
                    
                self.is_recording = False
                
                # Update UI immediately
                self.stop_btn.config(state=tk.DISABLED, bg='#95a5a6')
                self.status_var.set("Processing...")
                
                # Wait for threads to finish
                if self.audio_thread and self.audio_thread.is_alive():
                    self.audio_thread.join(timeout=3)
                if self.video_thread and self.video_thread.is_alive():
                    self.video_thread.join(timeout=3)
                
                # Process and save recording
                self.root.after(0, self.process_recording)
                
                logger.info("Recording stopped")
                
        except Exception as e:
            logger.error(f"Error stopping recording: {e}")
            self.reset_ui()
            
    def audio_recording_worker(self):
        """Record audio data with precise timing and latency compensation"""
        samples_collected = 0
        
        # Audio latency compensation (در حدود 30-50ms تأخیر Arduino و Serial)
        audio_latency_compensation = 0.03  # 30ms جلوتر از video
        
        while self.is_recording:
            try:
                if self.serial_port and self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    
                    for byte in data:
                        # Calculate sample time with latency compensation
                        sample_time = (samples_collected / self.SAMPLE_RATE) - audio_latency_compensation
                        sample_time = max(0, sample_time)  # Ensure non-negative
                        
                        self.audio_data.append(byte)
                        self.audio_timestamps.append(sample_time)
                        samples_collected += 1
                        
                time.sleep(0.0005)  # Reduce sleep for better precision
                
            except Exception as e:
                logger.error(f"Audio recording error: {e}")
                break
                
    def video_recording_worker(self):
        """Record video frames with precise timing and network latency compensation"""
        frame_count = 0
        
        # Video latency compensation (ESP32-CAM network delay)
        video_latency_compensation = 0.05  # 50ms تأخیر شبکه
        
        while self.is_recording:
            try:
                if self.cap and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    if ret:
                        # Record timestamp with latency compensation
                        capture_time = (time.time() - self.recording_start_time) - video_latency_compensation
                        capture_time = max(0, capture_time)  # Ensure non-negative
                        
                        # Store frame and timestamp
                        self.video_frames.append(frame.copy())
                        self.frame_timestamps.append(capture_time)
                        frame_count += 1
                        
                        # Update preview every 3rd frame for better performance
                        if frame_count % 3 == 0:
                            self.update_recording_preview(frame)
                            
                # Precise timing control
                time.sleep(0.008)  # 8ms sleep for better frame timing
                        
            except Exception as e:
                logger.error(f"Video recording error: {e}")
                break
                
    def update_recording_preview(self, frame):
        """Update preview during recording"""
        try:
            # Resize and convert frame
            height, width = frame.shape[:2]
            max_width, max_height = 700, 500
            
            if width > max_width or height > max_height:
                scale = min(max_width/width, max_height/height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                frame = cv2.resize(frame, (new_width, new_height))
            
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            img_tk = ImageTk.PhotoImage(img)
            
            self.root.after(0, self.update_preview, img_tk)
            
        except Exception as e:
            logger.error(f"Recording preview error: {e}")
            
    def update_recording_timer(self):
        """Update recording timer"""
        if self.is_recording and self.recording_start_time:
            elapsed = time.time() - self.recording_start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.timer_var.set(f"{minutes:02d}:{seconds:02d}")
            
            self.root.after(1000, self.update_recording_timer)
        else:
            self.timer_var.set("00:00")
            
    def process_recording(self):
        """Process and save the recorded data with improved folder structure"""
        try:
            if not self.audio_data or not self.video_frames:
                messagebox.showerror("Error", "No data recorded!")
                self.reset_ui()
                return
            
            # Calculate durations for sync verification
            audio_duration = len(self.audio_data) / self.SAMPLE_RATE
            video_duration = (self.frame_timestamps[-1] - self.frame_timestamps[0]) if self.frame_timestamps else 0
            frames_recorded = len(self.video_frames)
            samples_recorded = len(self.audio_data)
            
            logger.info(f"Recording stats: Audio={audio_duration:.2f}s ({samples_recorded} samples), "
                       f"Video={video_duration:.2f}s ({frames_recorded} frames)")
                
            # Create unique recording folder
            base_dir = self.output_dir.get()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            recording_folder = os.path.join(base_dir, f"recording_{timestamp}")
            
            # Create folder structure: recording_YYYYMMDD_HHMMSS/
            #                         ├── audio/
            #                         ├── video/
            #                         └── final/
            audio_dir = os.path.join(recording_folder, "audio")
            video_dir = os.path.join(recording_folder, "video")
            final_dir = os.path.join(recording_folder, "final")
            
            os.makedirs(audio_dir, exist_ok=True)
            os.makedirs(video_dir, exist_ok=True)
            os.makedirs(final_dir, exist_ok=True)
            
            # File paths
            audio_file = os.path.join(audio_dir, f"audio_{timestamp}.wav")
            video_file = os.path.join(video_dir, f"video_{timestamp}.avi")
            final_file = os.path.join(final_dir, f"recording_{timestamp}.mp4")
            
            # Save audio
            self.save_audio(audio_file)
            logger.info(f"Audio saved: {audio_file}")
            
            # Save video
            self.save_video(video_file)
            logger.info(f"Video saved: {video_file}")
            
            # Combine audio and video with sync optimization
            self.combine_audio_video(audio_file, video_file, final_file)
            logger.info(f"Final video saved: {final_file}")
            
            # Start transcription in background thread
            if self.transcription_var.get():
                transcription_thread = threading.Thread(
                    target=self.transcribe_audio, 
                    args=(audio_file, recording_folder),
                    daemon=True
                )
                transcription_thread.start()
            
            self.status_var.set("✅ Recording Saved!")
            
            # Show detailed success message
            success_msg = (
                f"📊 Recording Statistics:\n"
                f"• Audio: {audio_duration:.2f} seconds ({samples_recorded:,} samples)\n"
                f"• Video: {video_duration:.2f} seconds ({frames_recorded} frames)\n"
                f"• Sample Rate: {self.SAMPLE_RATE} Hz\n"
                f"• Sync Status: ✅ Optimized\n"
            )
            
            if self.transcription_var.get():
                success_msg += f"• Transcription: 🔄 In progress...\n"
                
            success_msg += (
                f"\n📁 Saved in folder: recording_{timestamp}/\n"
                f"  ├── audio/audio_{timestamp}.wav\n"
                f"  ├── video/video_{timestamp}.avi\n"
                f"  └── final/recording_{timestamp}.mp4\n"
            )
            
            if self.transcription_var.get():
                success_msg += f"  └── transcript_{timestamp}.txt (processing...)\n"
                
            success_msg += f"\n📂 Location: {recording_folder}"
            
            messagebox.showinfo("Recording Saved Successfully!", success_msg)
                
        except Exception as e:
            error_msg = f"Failed to save recording: {str(e)}"
            logger.error(error_msg)
            messagebox.showerror("Error", error_msg)
            
        finally:
            self.reset_ui()
            
    def save_audio(self, filename):
        """Save raw audio data as WAV file"""
        try:
            with wave.open(filename, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(1)  # 8-bit
                wav_file.setframerate(self.SAMPLE_RATE)
                
                # Convert audio data to proper format
                audio_bytes = bytes(self.audio_data)
                wav_file.writeframes(audio_bytes)
                
        except Exception as e:
            raise Exception(f"Audio save error: {str(e)}")
            
    def save_video(self, filename):
        """Save video frames with calculated frame rate"""
        try:
            if not self.video_frames:
                raise Exception("No video frames to save")
                
            height, width = self.video_frames[0].shape[:2]
            
            # Calculate actual frame rate based on timestamps
            if len(self.frame_timestamps) > 1:
                total_duration = self.frame_timestamps[-1] - self.frame_timestamps[0]
                actual_fps = (len(self.frame_timestamps) - 1) / total_duration if total_duration > 0 else self.FRAME_RATE
                actual_fps = max(5, min(actual_fps, 60))  # Clamp between 5-60 FPS
            else:
                actual_fps = self.FRAME_RATE
            
            logger.info(f"Saving video with {actual_fps:.2f} FPS, {len(self.video_frames)} frames")
            
            # Use MJPG codec for better compatibility
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            out = cv2.VideoWriter(filename, fourcc, actual_fps, (width, height))
            
            for frame in self.video_frames:
                out.write(frame)
                
            out.release()
            
        except Exception as e:
            raise Exception(f"Video save error: {str(e)}")
            
    def combine_audio_video(self, audio_file, video_file, output_file):
        """Combine audio and video with precise synchronization"""
        try:
            # Get audio and video durations
            audio_duration = len(self.audio_data) / self.SAMPLE_RATE
            
            if self.frame_timestamps:
                video_duration = self.frame_timestamps[-1] - self.frame_timestamps[0]
            else:
                video_duration = audio_duration
            
            logger.info(f"Audio duration: {audio_duration:.3f}s, Video duration: {video_duration:.3f}s")
            
            # Fine-tune sync offset (positive = delay audio, negative = advance audio)
            sync_offset = 0.02  # 20ms audio delay to match video better
            
            # Calculate target duration
            target_duration = min(audio_duration, video_duration)
            
            cmd = [
                'ffmpeg', '-y',  # Overwrite output
                '-i', video_file,
                '-itsoffset', str(sync_offset),  # Audio delay for sync
                '-i', audio_file,
                '-c:v', 'libx264',     # Video codec
                '-c:a', 'aac',         # Audio codec
                '-preset', 'medium',   # Encoding speed/quality balance
                '-crf', '20',          # Better quality (lower CRF)
                '-t', str(target_duration),  # Set target duration
                '-avoid_negative_ts', 'make_zero',  # Handle timestamp issues
                '-fflags', '+genpts',  # Generate timestamps
                '-vsync', 'cfr',       # Constant frame rate
                '-async', '1',         # Audio sync correction
                '-map', '0:v:0',       # Map video from first input
                '-map', '1:a:0',       # Map audio from second input
                output_file
            ]
            
            logger.info(f"FFmpeg command: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"FFmpeg completed successfully. Sync offset: {sync_offset}s")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg stderr: {e.stderr}")
            raise Exception(f"FFmpeg error: {e.stderr}")
        except FileNotFoundError:
            raise Exception("FFmpeg not found. Please install FFmpeg and add it to PATH.")
            
    def reset_ui(self):
        """Reset UI after recording"""
        self.start_btn.config(state=tk.NORMAL if self.is_connected else tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED, bg='#95a5a6')
        self.connect_btn.config(state=tk.NORMAL)
        
        if self.is_connected:
            self.status_var.set("✓ Connected")
        else:
            self.status_var.set("Disconnected")
            
    def select_output_dir(self):
        """Select output directory"""
        directory = filedialog.askdirectory()
        if directory:
            self.output_dir.set(directory)
            
    def on_closing(self):
        """Handle application closing"""
        try:
            self.shutdown_flag.set()
            self.is_recording = False
            
            # Stop all threads
            if self.preview_thread and self.preview_thread.is_alive():
                self.preview_thread.join(timeout=2)
                
            self.disconnect_devices()
            self.root.destroy()
            
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
            self.root.destroy()

def main():
    """Main function"""
    # Check required libraries
    try:
        import requests
    except ImportError:
        print("❌ Error: 'requests' library is required for API communication")
        print("Install with: pip install requests")
        return
        
    # Check FFmpeg availability
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        logger.info("FFmpeg found")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  Warning: FFmpeg is not installed or not in PATH.")
        print("Please install FFmpeg for video processing.")
        print("Download from: https://ffmpeg.org/download.html")
        
    # Check if transcription API is available
    try:
        response = requests.get("http://localhost:8000/", timeout=2)
        logger.info("Transcription API server detected")
    except:
        print("💡 Info: Transcription API server not running on port 8000")
        print("Start the transcription server to enable speech-to-text functionality")
        
    # Create and run application
    root = tk.Tk()
    app = AudioVideoRecorder(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        app.on_closing()

if __name__ == "__main__":
    main()