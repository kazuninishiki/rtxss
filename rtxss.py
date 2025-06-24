import sys
import subprocess
import psutil
import json
import threading
import time
import logging
import winreg
from datetime import datetime
from collections import deque
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import pystray
from PIL import Image, ImageDraw
import configparser
import os

# Configure enhanced logging for both console and file
log_dir = os.path.dirname(os.path.abspath(sys.executable if hasattr(sys, 'frozen') else __file__))
log_file = os.path.join(log_dir, 'rtxss.log')

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Setup file handler with rotation
from logging.handlers import RotatingFileHandler
file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG)

# Setup console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[file_handler, console_handler]
)

logger = logging.getLogger(__name__)

# Log startup information
logger.info("=" * 60)
logger.info("RTXSS (RTX System Stats) Starting Up")
logger.info("=" * 60)
logger.info(f"Python version: {sys.version}")
logger.info(f"Executable path: {sys.executable}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info(f"Log file: {log_file}")
logger.info(f"Running as compiled: {hasattr(sys, 'frozen')}")

class NvidiaDataCollector:
    def __init__(self):
        self.running = False
        self._graphics_warning_logged = False
        
    def get_gpu_data(self):
        """Get GPU information using nvidia-smi queries"""
        logger.debug("Starting GPU data collection")
        try:
            cmd = [
                'nvidia-smi', 
                '--query-gpu=index,name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory,temperature.gpu,power.draw,power.limit,fan.speed,pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max',
                '--format=csv,noheader,nounits'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            lines = result.stdout.strip().split('\n')
            
            # Get CUDA version
            cuda_version = "N/A"
            try:
                cuda_cmd = ['nvidia-smi', '--query-gpu=cuda_version', '--format=csv,noheader,nounits']
                cuda_result = subprocess.run(cuda_cmd, capture_output=True, text=True, check=False)
                if cuda_result.returncode == 0 and cuda_result.stdout.strip():
                    cuda_version = cuda_result.stdout.strip().split('\n')[0]
                else:
                    # Fallback: try to get CUDA version from nvidia-smi output
                    version_cmd = ['nvidia-smi']
                    version_result = subprocess.run(version_cmd, capture_output=True, text=True, check=False)
                    if version_result.returncode == 0:
                        for line in version_result.stdout.split('\n'):
                            if 'CUDA Version:' in line:
                                cuda_version = line.split('CUDA Version:')[1].strip().split()[0]
                                break
            except Exception as e:
                logger.warning(f"Failed to get CUDA version - {str(e)}")
            
            gpu_info = []
            for line in lines:
                if line.strip():
                    parts = [part.strip() for part in line.split(',')]
                    if len(parts) >= 16:
                        # Calculate GT/s based on PCIe generation
                        def get_gts(gen):
                            gen_map = {'1': 2.5, '2': 5.0, '3': 8.0, '4': 16.0, '5': 32.0, '6': 64.0}
                            return gen_map.get(str(gen).strip(), 0.0)
                        
                        current_gen = parts[12].strip()
                        max_gen = parts[13].strip()
                        current_width = parts[14].strip()
                        max_width = parts[15].strip()
                        
                        gpu_info.append({
                            'index': parts[0],
                            'name': parts[1],
                            'driver_version': parts[2],
                            'memory_total': parts[3],
                            'memory_used': parts[4],
                            'memory_free': parts[5],
                            'gpu_util': parts[6],
                            'memory_util': parts[7],
                            'temperature': parts[8],
                            'power_draw': parts[9],
                            'power_limit': parts[10],
                            'fan_speed': parts[11],
                            'pcie_gen_current': current_gen,
                            'pcie_gen_max': max_gen,
                            'pcie_width_current': current_width,
                            'pcie_width_max': max_width,
                            'pcie_gts_current': get_gts(current_gen),
                            'pcie_gts_max': get_gts(max_gen),
                            'cuda_version': cuda_version
                        })
            
            logger.debug(f"Successfully collected data for {len(gpu_info)} GPU(s)")
            return gpu_info
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get GPU data - nvidia-smi error - {str(e)}")
            logger.error(f"nvidia-smi stderr - {e.stderr if e.stderr else 'No stderr'}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error getting GPU data - {str(e)}")
            return []
    
    def get_process_data(self):
        """Get process information with CPU and RAM usage"""
        try:
            nvidia_processes = {}
            
            # Get compute processes
            try:
                cmd = ['nvidia-smi', '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits']
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        parts = line.split(',')
                        if len(parts) >= 2:
                            pid = parts[0].strip()
                            memory = parts[1].strip()
                            nvidia_processes[pid] = memory
                            
            except subprocess.CalledProcessError:
                pass
            
            # Try graphics processes
            try:
                cmd = ['nvidia-smi', '--query-graphics-apps=pid,used_memory', '--format=csv,noheader,nounits']
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        parts = line.split(',')
                        if len(parts) >= 2:
                            pid = parts[0].strip()
                            memory = parts[1].strip()
                            if pid not in nvidia_processes:
                                nvidia_processes[pid] = memory
                                
            except subprocess.CalledProcessError:
                if not self._graphics_warning_logged:
                    logger.info("Graphics apps query not supported, using alternative process detection")
                    self._graphics_warning_logged = True
            
            # Enrich with process details
            process_data = []
            for pid_str, gpu_memory in nvidia_processes.items():
                try:
                    pid = int(pid_str)
                    process = psutil.Process(pid)
                    
                    process_info = {
                        'pid': pid,
                        'name': process.name(),
                        'memory_percent': f"{process.memory_percent():.1f}"
                    }
                    process_data.append(process_info)
                    
                except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                    process_data.append({
                        'pid': pid_str,
                        'name': 'Unknown',
                        'memory_percent': 'N/A'
                    })
            
            return process_data
            
        except Exception as e:
            logger.error(f"Error getting process data - {str(e)}")
            return []

class NvidiaWebServer:
    def __init__(self):
        logger.info("Initializing NvidiaWebServer...")
        try:
            self.app = Flask(__name__)
            self.app.config['SECRET_KEY'] = 'nvidia_monitor_secret'
            logger.debug("Flask app created successfully")
            
            self.socketio = SocketIO(self.app, cors_allowed_origins="*")
            logger.debug("SocketIO initialized successfully")
            
            self.data_collector = NvidiaDataCollector()
            self.gpu_history = deque(maxlen=60)
            self.running = False
            self.connected_clients = 0
            self.update_interval = 1.0  # Default 1000ms
            
            logger.info("Setting up routes...")
            self.setup_routes()
            logger.info("Setting up SocketIO handlers...")
            self.setup_socketio()
            logger.info("NvidiaWebServer initialization complete")
            
        except Exception as e:
            logger.error(f"Failed to initialize NvidiaWebServer - {str(e)}")
            raise
        
    def setup_routes(self):
        @self.app.route('/')
        def index():
            return render_template_string(HTML_TEMPLATE)
        
        @self.app.route('/api/gpu_data')
        def get_gpu_data():
            gpu_data = self.data_collector.get_gpu_data()
            process_data = self.data_collector.get_process_data()
            
            return jsonify({
                'gpu_info': gpu_data,
                'processes': process_data,
                'timestamp': datetime.now().isoformat()
            })
        
        @self.app.route('/api/set_power', methods=['POST'])
        def set_power_limit():
            try:
                data = request.get_json()
                wattage = int(data.get('wattage', 500))
                
                if not 400 <= wattage <= 600:
                    return jsonify({'success': False, 'message': 'Power limit must be between 400W and 600W'})
                
                cmd = ['nvidia-smi', '-pl', str(wattage)]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                
                logger.info(f"Power limit set to {wattage}W successfully")
                return jsonify({'success': True, 'message': f'Power limit set to {wattage}W successfully'})
                
            except subprocess.CalledProcessError as e:
                error_msg = f"Failed to set power limit - {str(e)}"
                logger.error(error_msg)
        @self.app.route('/api/set_update_interval', methods=['POST'])
        def set_update_interval():
            try:
                data = request.get_json()
                interval = int(data.get('interval', 1000))
                
                if not 100 <= interval <= 10000:
                    return jsonify({'success': False, 'message': 'Update interval must be between 100ms and 10000ms'})
                
                self.update_interval = interval / 1000.0  # Convert to seconds
                logger.info(f"Update interval set to {interval}ms")
                return jsonify({'success': True, 'message': f'Update interval set to {interval}ms'})
                
            except Exception as e:
                error_msg = f"Error setting update interval - {str(e)}"
                logger.error(error_msg)
                return jsonify({'success': False, 'message': error_msg})
            except Exception as e:
                error_msg = f"Error - {str(e)}"
                logger.error(error_msg)
                return jsonify({'success': False, 'message': error_msg})
    
    def setup_socketio(self):
        @self.socketio.on('connect')
        def handle_connect():
            self.connected_clients += 1
            logger.info(f'Client connected - Total clients {self.connected_clients}')
            emit('status', {'message': 'Connected to NVIDIA GPU Monitor'})
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            self.connected_clients = max(0, self.connected_clients - 1)
            logger.info(f'Client disconnected - Total clients {self.connected_clients}')
    
    def update_data(self):
        """Background thread to collect and broadcast GPU data"""
        while self.running:
            try:
                gpu_data = self.data_collector.get_gpu_data()
                process_data = self.data_collector.get_process_data()
                
                if gpu_data:
                    # Store history for charts
                    self.gpu_history.append({
                        'timestamp': datetime.now().isoformat(),
                        'temperature': float(gpu_data[0]['temperature']),
                        'power': float(gpu_data[0]['power_draw'])
                    })
                
                # Broadcast to all connected clients
                self.socketio.emit('gpu_update', {
                    'gpu_info': gpu_data,
                    'processes': process_data,
                    'history': list(self.gpu_history),
                    'timestamp': datetime.now().isoformat(),
                    'client_count': self.connected_clients
                })
                
            except Exception as e:
                logger.error(f"Error in update_data - {str(e)}")
            
            time.sleep(self.update_interval)
    
    def start_server(self):
        logger.info("Starting NVIDIA GPU Monitor Web Server...")
        try:
            # Check if port 9876 is available
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex(('localhost', 9876))
            sock.close()
            
            if result == 0:
                logger.warning("Port 9876 is already in use!")
                logger.warning("Another instance might be running or port is blocked")
            else:
                logger.info("Port 9876 is available")
            
            self.running = True
            
            # Start data update thread
            logger.info("Starting data update thread...")
            update_thread = threading.Thread(target=self.update_data, daemon=True)
            update_thread.start()
            logger.info("Data update thread started successfully")
            
            # Test GPU data collection before starting server
            logger.info("Testing GPU data collection...")
            test_data = self.data_collector.get_gpu_data()
            if test_data:
                logger.info(f"GPU data test successful - found {len(test_data)} GPU(s)")
                for i, gpu in enumerate(test_data):
                    logger.info(f"GPU {i}: {gpu.get('name', 'Unknown')} - {gpu.get('driver_version', 'Unknown driver')}")
            else:
                logger.warning("GPU data test failed - no GPU data available")
            
            logger.info("Starting Flask-SocketIO server on http://0.0.0.0:9876")
            logger.info("Web interface will be available at:")
            logger.info("  Local: http://localhost:9876")
            logger.info("  Network: http://YOUR_IP_ADDRESS:9876")
            
            # Start the server with error handling
            self.socketio.run(
                self.app, 
                host='0.0.0.0', 
                port=9876, 
                debug=False,
                use_reloader=False,
                log_output=True,
                allow_unsafe_werkzeug=True
            )
            
        except Exception as e:
            logger.error(f"Failed to start server - {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def stop_server(self):
        self.running = False

class SystemTrayApp:
    def __init__(self):
        logger.info("Initializing SystemTrayApp...")
        try:
            self.server = NvidiaWebServer()
            self.server_thread = None
            logger.info("SystemTrayApp initialization complete")
        except Exception as e:
            logger.error(f"Failed to initialize SystemTrayApp - {str(e)}")
            raise
        
    def create_image(self):
        logger.debug("Creating system tray icon...")
        try:
            # Create a simple icon
            image = Image.new('RGB', (64, 64), color='black')
            draw = ImageDraw.Draw(image)
            draw.rectangle([16, 16, 48, 48], fill='green')
            draw.text((20, 25), 'GPU', fill='white')
            logger.debug("System tray icon created successfully")
            return image
        except Exception as e:
            logger.error(f"Failed to create tray icon - {str(e)}")
            # Return a minimal fallback icon
            return Image.new('RGB', (16, 16), color='green')
    
    def start_server(self, icon, item):
        logger.info("System tray: Start server requested")
        try:
            if self.server_thread is None or not self.server_thread.is_alive():
                logger.info("Starting server thread...")
                self.server_thread = threading.Thread(target=self.server.start_server, daemon=True)
                self.server_thread.start()
                logger.info("Server thread started")
                if icon:
                    icon.notify("NVIDIA GPU Monitor started on port 9876")
            else:
                logger.warning("Server thread already running")
                if icon:
                    icon.notify("Server is already running")
        except Exception as e:
            logger.error(f"Failed to start server from tray - {str(e)}")
            if icon:
                icon.notify(f"Failed to start server - {str(e)}")
    
    def stop_server(self, icon, item):
        logger.info("System tray: Stop server requested")
        try:
            self.server.stop_server()
            if icon:
                icon.notify("NVIDIA GPU Monitor stopped")
            logger.info("Server stopped")
        except Exception as e:
            logger.error(f"Failed to stop server - {str(e)}")
    
    def open_browser(self, icon, item):
        logger.info("System tray: Open browser requested")
        try:
            import webbrowser
            webbrowser.open('http://localhost:9876')
            logger.info("Browser opened to http://localhost:9876")
        except Exception as e:
            logger.error(f"Failed to open browser - {str(e)}")
            if icon:
                icon.notify(f"Failed to open browser - {str(e)}")
    
    def toggle_autostart(self, icon, item):
        try:
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
            app_name = "RTX System Stats"
            exe_path = os.path.abspath(sys.executable if hasattr(sys, 'frozen') else "rtxss.exe")
            
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
                try:
                    winreg.QueryValueEx(key, app_name)
                    # Key exists, remove it
                    winreg.DeleteValue(key, app_name)
                    icon.notify("Auto-start disabled")
                    logger.info("Auto-start disabled")
                except FileNotFoundError:
                    # Key doesn't exist, add it
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
                    icon.notify("Auto-start enabled")
                    logger.info("Auto-start enabled")
        except Exception as e:
            icon.notify(f"Error toggling auto-start - {str(e)}")
            logger.error(f"Error toggling auto-start - {str(e)}")
    
    def quit_app(self, icon, item):
        self.server.stop_server()
        icon.stop()
    
    def run(self):
        icon = pystray.Icon(
            "nvidia_monitor",
            self.create_image(),
            "NVIDIA GPU Monitor",
            pystray.Menu(
                pystray.MenuItem("Start Server", self.start_server),
                pystray.MenuItem("Stop Server", self.stop_server),
                pystray.MenuItem("Open Browser", self.open_browser),
                pystray.MenuItem("Toggle Auto-Start", self.toggle_autostart),
                pystray.MenuItem("Quit", self.quit_app)
            )
        )
        
        # Auto-start server
        self.start_server(icon, None)
        icon.run()

# HTML Template with Modular/Fluid Responsive Design - Panels Swapped
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>NVIDIA GPU Monitor</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        :root {
            --bg-primary: #1e1e1e;
            --bg-secondary: #2b2b2b;
            --bg-tertiary: #3b3b3b;
            --accent-color: #4a9eff;
            --accent-hover: #5ba7ff;
            --accent-active: #3a8edf;
            --border-color: #555;
            --text-primary: white;
            --text-secondary: #ccc;
            --success-color: #2ecc71;
            --error-color: #e74c3c;
            
            --spacing-xs: 0.25rem;
            --spacing-sm: 0.5rem;
            --spacing-md: 1rem;
            --spacing-lg: 1.5rem;
            --spacing-xl: 2rem;
            
            --border-radius: 0.5rem;
            --border-radius-sm: 0.25rem;
            
            --font-size-base: 0.875rem;
            --min-touch-target: 2.75rem;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.5;
            font-size: var(--font-size-base);
            -webkit-text-size-adjust: 100%;
            -webkit-tap-highlight-color: transparent;
        }
        
        .app-container {
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            max-width: 1920px;
            margin: 0 auto;
            padding: var(--spacing-sm);
            gap: var(--spacing-sm);
        }
        
        /* GPU Info Component */
        .gpu-section {
            background-color: var(--bg-secondary);
            border-radius: var(--border-radius);
            border: 1px solid var(--border-color);
            overflow: hidden;
            flex-shrink: 0;
        }
        
        /* Main Content Grid */
        .main-content {
            display: grid;
            gap: var(--spacing-sm);
            flex: 1;
            min-height: 0;
        }
        
        /* Panel Component */
        .panel {
            background-color: var(--bg-secondary);
            border-radius: var(--border-radius);
            border: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            min-height: 0;
            overflow: hidden;
        }
        
        .panel-header {
            padding: var(--spacing-md) var(--spacing-md) var(--spacing-sm);
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
        }
        
        .panel-title {
            color: var(--accent-color);
            font-size: var(--font-size-base);
            font-weight: bold;
            margin: 0;
        }
        
        .panel-content {
            padding: var(--spacing-md);
            flex: 1;
            overflow: auto;
            min-height: 0;
        }
        
        /* Table Component */
        .table-container {
            overflow: auto;
            -webkit-overflow-scrolling: touch;
            border-radius: var(--border-radius-sm);
            border: 1px solid var(--border-color);
        }
        
        /* Specific height constraints for different tables */
        .gpu-table-container {
            max-height: 60vh;
        }
        
        .process-table-container {
            max-height: 400px; /* Match approximate height of power control panel */
            overflow-y: auto;
            overflow-x: hidden;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: var(--font-size-base);
        }
        
        th, td {
            padding: var(--spacing-sm);
            text-align: left;
            border-bottom: 1px solid var(--border-color);
            font-size: var(--font-size-base);
        }
        
        th {
            background-color: var(--bg-tertiary);
            color: var(--accent-color);
            cursor: pointer;
            user-select: none;
            position: sticky;
            top: 0;
            z-index: 10;
            font-weight: bold;
            transition: background-color 0.2s;
        }
        
        th:hover {
            background-color: var(--border-color);
        }
        
        tr:hover {
            background-color: rgba(255, 255, 255, 0.05);
        }
        
        /* Chart Component */
        .chart-section {
            display: flex;
            flex-direction: column;
            gap: var(--spacing-md);
            flex: 1;
            min-height: 0;
        }
        
        .chart-container {
            position: relative;
            flex: 1;
            min-height: 150px;
            height: 0;
        }
        
        /* Power Control Component */
        .power-control {
            display: flex;
            flex-direction: column;
            gap: var(--spacing-md);
            min-width: 250px;
        }
        
        .power-status {
            padding: var(--spacing-sm);
            background-color: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: var(--border-radius-sm);
            font-weight: bold;
            color: var(--success-color);
            font-size: var(--font-size-base);
        }
        
        .power-section {
            display: flex;
            flex-direction: column;
            gap: var(--spacing-sm);
        }
        
        .power-section-title {
            font-size: var(--font-size-base);
            font-weight: bold;
            color: var(--text-secondary);
            margin-bottom: var(--spacing-xs);
        }
        
        .power-buttons {
            display: grid;
            gap: var(--spacing-sm);
            grid-template-columns: repeat(auto-fit, minmax(3rem, 1fr));
        }
        
        .power-log {
            background-color: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: var(--border-radius-sm);
            padding: var(--spacing-sm);
            font-family: 'Courier New', monospace;
            font-size: var(--font-size-base);
            overflow-y: auto;
            flex: 1;
            min-height: 100px;
            max-height: 200px;
            -webkit-overflow-scrolling: touch;
        }
        
        /* Button Component */
        .btn {
            background-color: var(--accent-color);
            color: var(--text-primary);
            border: none;
            padding: var(--spacing-sm) var(--spacing-md);
            border-radius: var(--border-radius-sm);
            cursor: pointer;
            font-weight: normal;
            font-size: var(--font-size-base);
            min-height: var(--min-touch-target);
            transition: all 0.2s;
            touch-action: manipulation;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .btn:hover {
            background-color: var(--accent-hover);
        }
        
        .btn:active {
            background-color: var(--accent-active);
            transform: scale(0.98);
        }
        
        /* Footer Component */
        .footer {
            background-color: var(--bg-secondary);
            padding: var(--spacing-sm) var(--spacing-md);
            border-radius: var(--border-radius);
            border: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: var(--spacing-sm);
            font-size: var(--font-size-base);
            color: var(--text-secondary);
            flex-shrink: 0;
        }
        
        .footer-info {
            display: flex;
            align-items: center;
            gap: var(--spacing-md);
            flex-wrap: wrap;
        }
        
        .interval-control {
            display: flex;
            align-items: center;
            gap: var(--spacing-xs);
        }
        
        .interval-input {
            background-color: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: var(--border-radius-sm);
            color: var(--text-primary);
            padding: var(--spacing-xs) var(--spacing-sm);
            width: 4rem;
            font-size: var(--font-size-base);
        }
        
        .interval-btn {
            background-color: var(--accent-color);
            color: var(--text-primary);
            border: none;
            padding: var(--spacing-xs) var(--spacing-sm);
            border-radius: var(--border-radius-sm);
            cursor: pointer;
            font-size: var(--font-size-base);
            min-height: auto;
            transition: all 0.2s;
        }
        
        .interval-btn:hover {
            background-color: var(--accent-hover);
        }
        
        /* Responsive Grid Layouts */
        @media (min-width: 1400px) {
            .main-content {
                grid-template-columns: minmax(280px, 1fr) minmax(500px, 2fr) minmax(280px, 1fr);
            }
        }
        
        @media (min-width: 1200px) and (max-width: 1399px) {
            .main-content {
                grid-template-columns: minmax(250px, 1fr) minmax(400px, 1.8fr) minmax(250px, 1fr);
            }
        }
        
        @media (min-width: 1000px) and (max-width: 1199px) {
            .main-content {
                grid-template-columns: minmax(220px, 1fr) minmax(300px, 1.5fr) minmax(220px, 1fr);
            }
        }
        
        @media (min-width: 800px) and (max-width: 999px) {
            .main-content {
                grid-template-columns: 1fr 1.5fr 1fr;
            }
        }
        
        @media (min-width: 768px) and (max-width: 799px) {
            .main-content {
                grid-template-columns: 1fr 1fr;
                grid-template-rows: auto auto;
            }
            
            .chart-panel {
                grid-column: 1 / -1;
            }
        }
        
        @media (max-width: 767px) {
            .app-container {
                padding: var(--spacing-xs);
                gap: var(--spacing-xs);
            }
            
            .main-content {
                grid-template-columns: 1fr;
            }
            
            .power-buttons {
                grid-template-columns: 1fr 1fr;
            }
            
            .chart-container {
                min-height: 120px;
            }
            
            .process-table-container {
                max-height: 300px; /* Smaller on mobile */
            }
            
            .footer {
                flex-direction: column;
                text-align: center;
            }
            
            .footer-info {
                justify-content: center;
            }
        }
        
        @media (max-width: 480px) {
            .power-buttons {
                grid-template-columns: 1fr;
            }
            
            .process-table-container {
                max-height: 250px; /* Even smaller on very small screens */
            }
        }
        
        /* High zoom / small viewport adjustments */
        @media (max-height: 600px) {
            .chart-container {
                min-height: 100px;
            }
            
            .power-log {
                min-height: 60px;
                max-height: 100px;
            }
            
            .process-table-container {
                max-height: 200px; /* Reduce when viewport height is limited */
            }
        }
        
        /* Zoom-specific adjustments for fluid panels */
        .power-control {
            display: flex;
            flex-direction: column;
            gap: var(--spacing-md);
            min-width: 200px;
            max-width: 100%;
        }
        
        /* Make panels more flexible */
        .panel {
            background-color: var(--bg-secondary);
            border-radius: var(--border-radius);
            border: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            min-height: 0;
            overflow: hidden;
            min-width: 0; /* Allow panels to shrink below content width */
        }
        
        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        
        ::-webkit-scrollbar-track {
            background: var(--bg-secondary);
        }
        
        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 3px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-secondary);
        }
        
        /* Print styles */
        @media print {
            body {
                background: white;
                color: black;
            }
        }
        
        /* Reduced motion preference */
        @media (prefers-reduced-motion: reduce) {
            * {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
            }
        }
    </style>
</head>
<body>
    <div class="app-container">
        <section class="gpu-section">
            <div class="table-container gpu-table-container">
                <table id="gpuTable">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Temp</th>
                            <th>Fan</th>
                            <th>Power</th>
                            <th>GPU%</th>
                            <th>Mem%</th>
                            <th>Memory</th>
                            <th>PCIe Gen</th>
                            <th>Lanes</th>
                            <th>GT/s</th>
                            <th>Driver</th>
                            <th>CUDA</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </section>
        
        <main class="main-content">
            <section class="panel">
                <div class="panel-header">
                    <h2 class="panel-title">Control</h2>
                </div>
                <div class="panel-content">
                    <div class="power-control">
                        <div class="power-status" id="currentPowerLimit">Max Wattage: Unknown</div>
                        <div class="power-status" id="currentTemperature">Temperature: --°C</div>
                        <div class="power-status" id="currentPower">Current: --W</div>
                        
                        <div class="power-section">
                            <div class="power-section-title">Power Limits</div>
                            <div class="power-buttons">
                                <button class="btn" onclick="setPowerLimit(400)" ontouchstart="">400W</button>
                                <button class="btn" onclick="setPowerLimit(450)" ontouchstart="">450W</button>
                                <button class="btn" onclick="setPowerLimit(500)" ontouchstart="">500W</button>
                                <button class="btn" onclick="setPowerLimit(550)" ontouchstart="">550W</button>
                                <button class="btn" onclick="setPowerLimit(600)" ontouchstart="">600W</button>
                            </div>
                        </div>
                        
                        <div class="power-section">
                            <div class="power-section-title">Status Log</div>
                            <div class="power-log" id="powerLog"></div>
                        </div>
                    </div>
                </div>
            </section>
            
            <section class="panel chart-panel">
                <div class="panel-header">
                    <h2 class="panel-title">GPU Metrics History</h2>
                </div>
                <div class="panel-content">
                    <div class="chart-section">
                        <div class="chart-container">
                            <canvas id="temperatureChart"></canvas>
                        </div>
                        <div class="chart-container">
                            <canvas id="powerChart"></canvas>
                        </div>
                    </div>
                </div>
            </section>
            
            <section class="panel">
                <div class="panel-header">
                    <h2 class="panel-title">GPU Processes</h2>
                </div>
                <div class="panel-content">
                    <div class="table-container process-table-container">
                        <table id="processTable">
                            <thead>
                                <tr>
                                    <th onclick="sortTable(0)" ontouchstart="">Process</th>
                                    <th onclick="sortTable(1)" ontouchstart="">RAM%</th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                    </div>
                </div>
            </section>
        </main>
        
        <footer class="footer">
            <div class="footer-info">
                <div>Last Update: <span id="lastUpdate">Never</span></div>
                <div>Clients: <span id="clientCount">0</span></div>
            </div>
            <div class="interval-control">
                <span>Update (ms):</span>
                <input type="number" id="intervalInput" class="interval-input" value="1000" min="100" max="10000" step="100">
                <button class="interval-btn" onclick="setUpdateInterval()">Set</button>
            </div>
        </footer>
    </div>

    <script>
        const socket = io();
        let temperatureChart, powerChart;
        let sortDirection = {};
        
        // Prevent double-tap zoom on mobile
        let lastTouchEnd = 0;
        document.addEventListener('touchend', function (event) {
            const now = Date.now();
            if (now - lastTouchEnd <= 300) {
                event.preventDefault();
            }
            lastTouchEnd = now;
        }, false);
        
        // Initialize charts with responsive options
        function initCharts() {
            const tempCtx = document.getElementById('temperatureChart').getContext('2d');
            const powerCtx = document.getElementById('powerChart').getContext('2d');
            
            const chartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                plugins: {
                    legend: { 
                        labels: { 
                            color: 'white',
                            font: { size: 14 }
                        }
                    }
                },
                scales: {
                    x: { 
                        ticks: { 
                            color: 'white',
                            font: { size: 14 },
                            maxTicksLimit: 8
                        }, 
                        grid: { color: '#555' }
                    },
                    y: { 
                        ticks: { 
                            color: 'white',
                            font: { size: 14 }
                        }, 
                        grid: { color: '#555' }
                    }
                },
                elements: {
                    point: {
                        radius: 1,
                        hoverRadius: 3
                    },
                    line: {
                        borderWidth: 2
                    }
                }
            };
            
            temperatureChart = new Chart(tempCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Temperature (°C)',
                        data: [],
                        borderColor: '#ff6b6b',
                        backgroundColor: 'rgba(255, 107, 107, 0.1)',
                        tension: 0.4
                    }]
                },
                options: chartOptions
            });
            
            powerChart = new Chart(powerCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Power (W)',
                        data: [],
                        borderColor: '#4ecdc4',
                        backgroundColor: 'rgba(78, 205, 196, 0.1)',
                        tension: 0.4
                    }]
                },
                options: chartOptions
            });
        }
        
        // Socket event handlers
        socket.on('connect', function() {
            addToLog('Connected');
        });
        
        socket.on('disconnect', function() {
            addToLog('Disconnected');
        });
        
        socket.on('gpu_update', function(data) {
            updateGPUInfo(data.gpu_info);
            updateProcessTable(data.processes);
            updateCharts(data.history);
            document.getElementById('lastUpdate').textContent = new Date(data.timestamp).toLocaleTimeString();
            document.getElementById('clientCount').textContent = data.client_count || 0;
        });
        
        function updateGPUInfo(gpuInfo) {
            const tbody = document.querySelector('#gpuTable tbody');
            tbody.innerHTML = '';
            
            if (gpuInfo && gpuInfo.length > 0) {
                const gpu = gpuInfo[0];
                
                document.getElementById('currentPowerLimit').textContent = 
                    `Max Wattage: ${gpu.power_limit}W`;
                document.getElementById('currentTemperature').textContent = 
                    `Temperature: ${gpu.temperature}°C`;
                document.getElementById('currentPower').textContent = 
                    `Current: ${gpu.power_draw}W`;
                
                const row = tbody.insertRow();
                row.innerHTML = `
                    <td>${gpu.name.split(' ').slice(-2).join(' ')}</td>
                    <td>${gpu.temperature}°C</td>
                    <td>${gpu.fan_speed}%</td>
                    <td>${gpu.power_draw}W</td>
                    <td>${gpu.gpu_util}%</td>
                    <td>${gpu.memory_util}%</td>
                    <td>${gpu.memory_used}MB</td>
                    <td>${gpu.pcie_gen_current}/${gpu.pcie_gen_max}</td>
                    <td>x${gpu.pcie_width_current}/x${gpu.pcie_width_max}</td>
                    <td>${gpu.pcie_gts_current}/${gpu.pcie_gts_max}</td>
                    <td>${gpu.driver_version}</td>
                    <td>${gpu.cuda_version}</td>
                `;
            }
        }
        
        function updateProcessTable(processes) {
            const tbody = document.querySelector('#processTable tbody');
            tbody.innerHTML = '';
            
            processes.forEach(proc => {
                const row = tbody.insertRow();
                row.innerHTML = `
                    <td>${proc.name}</td>
                    <td>${proc.memory_percent}</td>
                `;
            });
        }
        
        function updateCharts(history) {
            if (!history || history.length === 0) return;
            
            const labels = history.map(h => new Date(h.timestamp).toLocaleTimeString().slice(0, 5));
            const tempData = history.map(h => h.temperature);
            const powerData = history.map(h => h.power);
            
            // Update temperature chart
            temperatureChart.data.labels = labels;
            temperatureChart.data.datasets[0].data = tempData;
            temperatureChart.data.datasets[0].label = `Temp ${tempData[tempData.length-1]}°C`;
            temperatureChart.update('none');
            
            // Update power chart
            powerChart.data.labels = labels;
            powerChart.data.datasets[0].data = powerData;
            powerChart.data.datasets[0].label = `Power ${powerData[powerData.length-1]}W`;
            powerChart.update('none');
        }
        
        function setPowerLimit(wattage) {
            // Visual feedback
            if (event && event.target) {
                event.target.style.transform = 'scale(0.98)';
                setTimeout(() => event.target.style.transform = '', 100);
            }
            
            fetch('/api/set_power', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ wattage: wattage })
            })
            .then(response => response.json())
            .then(data => {
                addToLog(data.message);
            })
            .catch(error => addToLog('Error ' + error));
        }
        
        function setUpdateInterval() {
            const interval = parseInt(document.getElementById('intervalInput').value);
            if (interval < 100 || interval > 10000) {
                addToLog('Invalid interval. Must be 100-10000ms');
                return;
            }
            
            fetch('/api/set_update_interval', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ interval: interval })
            })
            .then(response => response.json())
            .then(data => {
                addToLog(data.message);
            })
            .catch(error => addToLog('Error ' + error));
        }
        
        function addToLog(message) {
            const log = document.getElementById('powerLog');
            const timestamp = new Date().toLocaleTimeString().slice(0, 5);
            log.innerHTML += `${timestamp} - ${message}<br>`;
            log.scrollTop = log.scrollHeight;
        }
        
        function sortTable(columnIndex) {
            const table = document.getElementById('processTable');
            const tbody = table.getElementsByTagName('tbody')[0];
            const rows = Array.from(tbody.rows);
            
            const isAscending = sortDirection[columnIndex] !== true;
            sortDirection[columnIndex] = isAscending;
            
            rows.sort((a, b) => {
                const aVal = a.cells[columnIndex].textContent;
                const bVal = b.cells[columnIndex].textContent;
                
                const aNum = parseFloat(aVal);
                const bNum = parseFloat(bVal);
                
                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return isAscending ? aNum - bNum : bNum - aNum;
                } else {
                    return isAscending ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
                }
            });
            
            tbody.innerHTML = '';
            rows.forEach(row => tbody.appendChild(row));
        }
        
        // Initialize when page loads
        document.addEventListener('DOMContentLoaded', function() {
            initCharts();
            addToLog('Interface ready');
            
            // Add Enter key support for interval input
            document.getElementById('intervalInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    setUpdateInterval();
                }
            });
        });
        
        // Handle resize and orientation changes
        function handleResize() {
            setTimeout(() => {
                if (temperatureChart) temperatureChart.resize();
                if (powerChart) powerChart.resize();
            }, 300);
        }
        
        window.addEventListener('resize', handleResize);
        window.addEventListener('orientationchange', handleResize);
    </script>
</body>
</html>
'''

def main():
    # Check if nvidia-smi is available
    try:
        subprocess.run(['nvidia-smi', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error nvidia-smi not found. Please ensure NVIDIA drivers are installed.")
        sys.exit(1)
    
    print("Starting NVIDIA GPU Monitor Web Server...")
    print("The server will run in the system tray.")
    print("Access the web interface at http://localhost:9876")
    print("For remote access, use http://YOUR_IP_ADDRESS:9876")
    
    app = SystemTrayApp()
    app.run()

if __name__ == '__main__':
    main()