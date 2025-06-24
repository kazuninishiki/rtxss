#!/usr/bin/env python3
"""
RTXSS (RTX System Stats) Compiler Script
Compiles the NVIDIA GPU Monitor server into a standalone executable
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

def log_info(message):
    """Log information with timestamp"""
    print(f"[INFO] {message}")

def log_error(message):
    """Log error with timestamp"""
    print(f"[ERROR] {message}")

def run_command(command, check=True):
    """Run a command and return the result"""
    log_info(f"Running: {' '.join(command) if isinstance(command, list) else command}")
    try:
        result = subprocess.run(command, shell=True, check=check, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        return result
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {e}")
        if e.stderr:
            print(e.stderr)
        raise

def check_running_processes():
    """Check if rtxss.exe is currently running"""
    log_info("Checking for running rtxss.exe processes...")
    
    try:
        import psutil
        running_processes = []
        
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                if proc.info['name'] and 'rtxss' in proc.info['name'].lower():
                    running_processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        if running_processes:
            log_error("Found running rtxss.exe processes:")
            for proc in running_processes:
                log_error(f"  PID {proc.pid}: {proc.info['name']}")
            
            response = input("Kill running processes before compilation? (y/n): ").lower().strip()
            if response == 'y':
                for proc in running_processes:
                    try:
                        log_info(f"Terminating PID {proc.pid}")
                        proc.terminate()
                        proc.wait(timeout=5)
                    except:
                        try:
                            proc.kill()
                        except:
                            pass
                log_info("Processes terminated")
            else:
                log_error("Cannot compile while rtxss.exe is running. Please close it first.")
                return False
        else:
            log_info("No running rtxss.exe processes found")
        
        return True
        
    except ImportError:
        log_info("psutil not available, skipping process check")
        return True
    except Exception as e:
        log_error(f"Error checking processes: {e}")
        return True  # Continue anyway

def check_dependencies():
    """Check if required tools are installed"""
    log_info("Checking dependencies...")
    
    # Check Python
    try:
        python_version = sys.version_info
        if python_version.major < 3 or (python_version.major == 3 and python_version.minor < 8):
            raise Exception("Python 3.8+ required")
        log_info(f"Python {python_version.major}.{python_version.minor}.{python_version.micro} ✓")
    except Exception as e:
        log_error(f"Python check failed: {e}")
        return False
    
    # Check pip
    try:
        run_command([sys.executable, "-m", "pip", "--version"])
        log_info("pip ✓")
    except:
        log_error("pip not found")
        return False
    
    return True

def install_build_dependencies():
    """Install PyInstaller and other build dependencies"""
    log_info("Installing build dependencies...")
    
    build_deps = [
        "pyinstaller>=5.0",
        "flask>=2.0.0",
        "flask-socketio>=5.0.0", 
        "psutil>=5.8.0",
        "pystray>=0.19.0",
        "pillow>=9.0.0",
        "python-socketio>=5.0.0",
        "python-engineio>=4.0.0"
    ]
    
    for dep in build_deps:
        try:
            log_info(f"Installing {dep}")
            run_command([sys.executable, "-m", "pip", "install", dep])
        except Exception as e:
            log_error(f"Failed to install {dep}: {e}")
            return False
    
    return True

def create_icon():
    """Create a simple icon for the executable"""
    log_info("Creating application icon...")
    
    try:
        from PIL import Image, ImageDraw
        
        # Create a 256x256 icon
        size = 256
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Draw a simple GPU-like icon
        margin = size // 8
        # Main body
        draw.rectangle([margin, margin*2, size-margin, size-margin*2], fill='#76B900', outline='#5A8700', width=3)
        # Memory modules
        for i in range(3):
            y = margin*2 + 20 + i*30
            draw.rectangle([margin*1.5, y, size-margin*1.5, y+20], fill='#4CAF50', outline='#2E7D32', width=2)
        # Connector
        draw.rectangle([margin*2, size-margin*1.5, size-margin*2, size-margin], fill='#FFC107', outline='#F57F17', width=2)
        
        # Add text
        try:
            # Try to use a better font if available
            from PIL import ImageFont
            font_size = size // 12
            font = ImageFont.load_default()
        except:
            font = None
        
        text = "RTX"
        if font:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        else:
            text_width = len(text) * 8
            text_height = 11
        
        text_x = (size - text_width) // 2
        text_y = size - margin - text_height - 10
        
        draw.text((text_x, text_y), text, fill='white', font=font)
        
        # Save as ICO
        icon_path = "rtxss_icon.ico"
        # Convert to appropriate sizes for ICO
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        images = []
        for icon_size in sizes:
            resized = image.resize(icon_size, Image.Resampling.LANCZOS)
            images.append(resized)
        
        images[0].save(icon_path, format='ICO', sizes=[(img.size[0], img.size[1]) for img in images], append_images=images[1:])
        log_info(f"Icon created: {icon_path}")
        return icon_path
        
    except Exception as e:
        log_error(f"Failed to create icon: {e}")
        return None

def create_patched_script(main_script):
    """Create a patched version of the script for compilation"""
    log_info("Creating patched script for Windows compilation...")
    
    # Read the original script
    with open(main_script, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find a good insertion point after imports but before classes
    insertion_point = content.find('# Configure enhanced logging')
    if insertion_point == -1:
        insertion_point = content.find('class RTSSDataCollector')
    if insertion_point == -1:
        insertion_point = content.find('class NvidiaDataCollector')
    if insertion_point == -1:
        insertion_point = content.find('logging.basicConfig')
    
    if insertion_point != -1:
        # Insert the subprocess patch before the main code
        subprocess_patch = '''
# Windows subprocess patches to hide console windows
import platform
if platform.system() == 'Windows':
    import subprocess
    
    # Patch subprocess.run
    _original_run = subprocess.run
    def _patched_run(*args, **kwargs):
        if 'creationflags' not in kwargs:
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        return _original_run(*args, **kwargs)
    subprocess.run = _patched_run
    
    # Patch subprocess.Popen
    _original_popen = subprocess.Popen
    def _patched_popen(*args, **kwargs):
        if 'creationflags' not in kwargs:
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        return _original_popen(*args, **kwargs)
    subprocess.Popen = _patched_popen

'''
        # Insert the patch at the found position
        content = content[:insertion_point] + subprocess_patch + content[insertion_point:]
    else:
        # Fallback: append to the beginning after imports
        lines = content.split('\n')
        import_end = 0
        for i, line in enumerate(lines):
            if line.strip() and not (line.startswith('import ') or line.startswith('from ') or line.startswith('#')):
                import_end = i
                break
        
        patch_lines = [
            '',
            '# Windows subprocess patches to hide console windows',
            'import platform',
            'if platform.system() == "Windows":',
            '    import subprocess',
            '    _original_run = subprocess.run',
            '    def _patched_run(*args, **kwargs):',
            '        if "creationflags" not in kwargs:',
            '            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW',
            '        return _original_run(*args, **kwargs)',
            '    subprocess.run = _patched_run',
            '    _original_popen = subprocess.Popen',
            '    def _patched_popen(*args, **kwargs):',
            '        if "creationflags" not in kwargs:',
            '            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW',
            '        return _original_popen(*args, **kwargs)',
            '    subprocess.Popen = _patched_popen',
            ''
        ]
        
        lines = lines[:import_end] + patch_lines + lines[import_end:]
        content = '\n'.join(lines)
    
    # Write patched script
    patched_script = 'rtxss-compiled.py'
    with open(patched_script, 'w', encoding='utf-8') as f:
        f.write(content)
    
    log_info(f"Patched script created: {patched_script}")
    return patched_script

def create_spec_file(main_script, icon_path=None):
    """Create PyInstaller spec file for customization"""
    log_info("Creating PyInstaller spec file...")
    
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

import sys
import os

block_cipher = None

# Add hidden imports for modules that PyInstaller might miss
hidden_imports = [
    'engineio.async_drivers.threading',
    'socketio',
    'flask_socketio',
    'dns',
    'dns.resolver',
    'dns.asyncresolver',
    'psutil._psutil_windows',
    'PIL._tkinter_finder',
    'queue',
    'winreg',
    'platform'
]

a = Analysis(
    ['{main_script}'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'jupyter',
        'IPython',
        'pytest',
        'setuptools',
        'unittest',
        'test'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='rtxss',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
    {'icon=["' + icon_path + '"],' if icon_path else ''}
)
'''
    
    with open('rtxss.spec', 'w') as f:
        f.write(spec_content)
    
    return 'rtxss.spec'

def compile_executable(main_script):
    """Compile the Python script into a standalone executable"""
    log_info("Compiling executable...")
    
    # Create patched script for Windows subprocess handling
    patched_script = create_patched_script(main_script)
    
    # Create icon
    icon_path = create_icon()
    
    # Create spec file for better control
    spec_file = create_spec_file(patched_script, icon_path)
    
    # Build command
    build_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        spec_file
    ]
    
    try:
        # Run PyInstaller
        result = run_command(build_cmd)
        
        # Check if executable was created
        exe_path = Path("dist") / "rtxss.exe"
        if exe_path.exists():
            log_info(f"Executable created successfully: {exe_path}")
            
            # Get file size
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            log_info(f"Executable size: {size_mb:.1f} MB")
            
            return str(exe_path)
        else:
            log_error("Executable not found in dist folder")
            return None
            
    except Exception as e:
        log_error(f"Compilation failed: {e}")
        return None

def cleanup_build_files():
    """Clean up temporary build files"""
    log_info("Cleaning up build files...")
    
    cleanup_items = [
        "build",
        "__pycache__",
        "rtxss.spec",
        "rtxss_icon.ico",
        "rtxss-compiled.py"
    ]
    
    for item in cleanup_items:
        if os.path.exists(item):
            if os.path.isdir(item):
                shutil.rmtree(item)
            else:
                os.remove(item)
            log_info(f"Removed: {item}")

def main():
    """Main compilation process"""
    print("=" * 60)
    print("RTXSS (RTX System Stats) Compiler")
    print("=" * 60)
    
    # Check if main script exists
    main_script = "rtxss.py"
    if not os.path.exists(main_script):
        log_error(f"Main script not found: {main_script}")
        log_info("Please ensure the Python script is in the current directory")
        return 1
    
    try:
        # Step 1: Check for running processes
        if not check_running_processes():
            return 1
        
        # Step 2: Check dependencies
        if not check_dependencies():
            log_error("Dependency check failed")
            return 1
        
        # Step 3: Install build dependencies
        if not install_build_dependencies():
            log_error("Failed to install build dependencies")
            return 1
        
        # Step 4: Compile executable
        exe_path = compile_executable(main_script)
        if not exe_path:
            log_error("Compilation failed")
            return 1
        
        # Step 5: Success message
        print("\n" + "=" * 60)
        print("COMPILATION SUCCESSFUL!")
        print("=" * 60)
        log_info(f"Executable: {exe_path}")
        log_info("The executable is completely standalone and includes all dependencies")
        log_info("You can distribute this single file without any additional requirements")
        log_info("Settings and logs will be saved in the same folder as the executable")
        
        # Optional cleanup
        cleanup_choice = input("\nClean up build files? (y/n): ").lower().strip()
        if cleanup_choice == 'y':
            cleanup_build_files()
        
        return 0
        
    except KeyboardInterrupt:
        log_info("Compilation cancelled by user")
        return 1
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())