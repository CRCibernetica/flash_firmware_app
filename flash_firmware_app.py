import tkinter as tk
from tkinter import scrolledtext, messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import os
import subprocess
import threading
import serial
import serial.tools.list_ports
import queue
import re
import time

class FirmwareFlasherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Instalador IdeaBoard")
        self.root.geometry("800x600")  # Increased window size
        self.style = ttk.Style("litera")

        # Firmware file and baud rates
        self.firmware = "ideaboardfirmware03202025.bin"
        self.flash_baud_rate = "921600"
        self.serial_baud_rate = 115200

        # Queue for thread-safe communication
        self.output_queue = queue.Queue()

        # Serial connection
        self.serial_port = None
        self.serial_thread = None
        self.serial_running = False

        # GUI Layout
        self.setup_ui()

        # Check for output periodically
        self.check_queue()

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_ui(self):
        """Set up the modern UI layout with larger elements."""
        # Main container
        main_frame = ttk.Frame(self.root, padding=20)  # Increased padding
        main_frame.pack(fill=BOTH, expand=True)

        # Header
        header_label = ttk.Label(
            main_frame, text="Instalador IdeaBoard", font=("Helvetica", 20, "bold")  # Larger font
        )
        header_label.pack(pady=(0, 20))  # Increased padding

        # Control frame
        control_frame = ttk.LabelFrame(main_frame, text="Control", padding=15)  # Larger padding
        control_frame.pack(fill=X, pady=10)

        self.write_button = ttk.Button(
            control_frame,
            text="Instalar Firmware",
            command=self.start_flash,
            style="primary.TButton",
            width=25  # Wider button
        )
        self.write_button.configure(style="large.primary.TButton")  # Custom larger button style
        self.write_button.pack(pady=10)

        # Status label
        self.status_var = tk.StringVar(value="Listo")
        status_label = ttk.Label(
            control_frame,
            textvariable=self.status_var,
            font=("Helvetica", 12),  # Larger font
            bootstyle="info"
        )
        status_label.pack(pady=10)

        # Terminal frame
        terminal_frame = ttk.LabelFrame(main_frame, text="Consola", padding=15)  # Larger padding
        terminal_frame.pack(fill=BOTH, expand=True, pady=10)

        self.terminal = scrolledtext.ScrolledText(
            terminal_frame,
            height=22,  # Slightly taller
            font=("Consolas", 12),  # Larger font
            wrap=tk.WORD,
            bg="#2e2e2e",
            fg="#ffffff",
            insertbackground="white"
        )
        self.terminal.pack(fill=BOTH, expand=True)
        self.terminal.config(state="disabled")

        # Configure larger button style
        self.style.configure("large.primary.TButton", font=("Helvetica", 14))  # Larger button font

    def log(self, message):
        """Append message to the terminal widget."""
        self.terminal.config(state="normal")
        self.terminal.insert(tk.END, message + "\n")
        self.terminal.see(tk.END)
        self.terminal.config(state="disabled")

    def check_queue(self):
        """Check the queue for new messages."""
        try:
            while True:
                message = self.output_queue.get_nowait()
                self.log(message)
        except queue.Empty:
            pass
        self.root.after(100, self.check_queue)

    def start_flash(self):
        """Start the flashing process in a separate thread."""
        self.write_button.config(state="disabled")
        self.status_var.set("Instalando...")
        self.log("Starting firmware flashing process...")
        # Stop any existing serial reading
        self.serial_running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            self.serial_port = None
        threading.Thread(target=self.flash_firmware, daemon=True).start()

    def run_command(self, cmd):
        """Run a command and stream its output to the queue."""
        try:
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            for line in process.stdout:
                self.output_queue.put(line.strip())
            for line in process.stderr:
                self.output_queue.put(line.strip())
            process.wait()
            if process.returncode != 0:
                self.output_queue.put(f"Command failed with return code {process.returncode}")
                return False
            return True
        except Exception as e:
            self.output_queue.put(f"Error running command: {str(e)}")
            return False

    def strip_ansi_codes(self, text):
        """Remove ANSI escape codes from text."""
        ansi_pattern = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_pattern.sub('', text)

    def read_serial(self, port):
        """Read from the serial port and send to the queue."""
        try:
            self.serial_port = serial.Serial(port, self.serial_baud_rate, timeout=1)
            self.serial_running = True
            self.output_queue.put("Reading serial output...")
            while self.serial_running:
                if self.serial_port.in_waiting > 0:
                    line = self.serial_port.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        clean_line = self.strip_ansi_codes(line)
                        if clean_line:
                            self.output_queue.put(clean_line)
        except serial.SerialException as e:
            self.output_queue.put(f"Serial error: {str(e)}")
        except Exception as e:
            self.output_queue.put(f"Error reading serial: {str(e)}")
        finally:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()

    def try_open_port(self, port, retries=3, delay=2):
        """Attempt to open a serial port with retries."""
        for attempt in range(retries):
            try:
                ser = serial.Serial(port, self.serial_baud_rate, timeout=1)
                ser.close()
                return True
            except serial.SerialException as e:
                self.output_queue.put(f"Attempt {attempt + 1}/{retries} to open {port} failed: {str(e)}")
                if attempt < retries - 1:
                    time.sleep(delay)
        return False

    def select_port(self, ports):
        """Prompt user to select a port from available ports."""
        port_list = [port.device for port in ports]
        if not port_list:
            messagebox.showerror("Error", "No serial ports available. Please check your connections.")
            return None

        dialog = ttk.Window(self.root, title="Select Serial Port", minsize=(400, 250))  # Larger dialog
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Select a serial port:", font=("Helvetica", 12)).pack(pady=15)  # Larger font
        selected_port = tk.StringVar(value=port_list[0])
        for port in port_list:
            ttk.Radiobutton(
                dialog, text=port, variable=selected_port, value=port, font=("Helvetica", 11)
            ).pack(anchor="w", padx=30, pady=5)

        def on_ok():
            dialog.destroy()

        ttk.Button(dialog, text="OK", command=on_ok, style="large.primary.TButton").pack(pady=15)
        self.root.wait_window(dialog)
        return selected_port.get()

    def flash_firmware(self):
        """Execute the firmware flashing process and start serial reading."""
        try:
            # Get a list of all the serial ports
            ports = list(serial.tools.list_ports.comports())
            if not ports:
                self.output_queue.put("No serial ports found.")
                self.status_var.set("Error: No ports")
                return

            # Find the CH340 port
            ch340_port = None
            for port in ports:
                self.output_queue.put(f"Port: {port.device}, Description: {port.description}")
                if "CH340" in port.description:
                    ch340_port = port.device
                    break

            if ch340_port is None:
                self.output_queue.put("No CH340 port found. Prompting for port selection...")
                ch340_port = self.select_port(ports)
                if not ch340_port:
                    self.output_queue.put("No port selected. Aborting.")
                    self.status_var.set("Error: No port selected")
                    return

            self.output_queue.put(f"Using port: {ch340_port}")

            # Try to open the port to check if it's accessible
            if not self.try_open_port(ch340_port):
                self.output_queue.put(f"Could not access {ch340_port}. Prompting for port selection...")
                ch340_port = self.select_port(ports)
                if not ch340_port:
                    self.output_queue.put("No port selected. Aborting.")
                    self.status_var.set("Error: No port selected")
                    return
                if not self.try_open_port(ch340_port):
                    self.output_queue.put(f"Could not access {ch340_port}. Aborting.")
                    self.status_var.set("Error: Port inaccessible")
                    return

            # Commands
            erase_cmd = f"python -m esptool --chip esp32 --port {ch340_port} erase_flash"
            write_cmd = f"python -m esptool --chip esp32 --port {ch340_port} --baud {self.flash_baud_rate} write_flash 0x0 {self.firmware}"

            # Erase flash memory
            self.output_queue.put("Erasing flash memory...")
            if not self.run_command(erase_cmd):
                self.output_queue.put("Erase failed.")
                self.status_var.set("Error: Erase failed")
                return

            # Write the firmware
            self.output_queue.put("Writing flash memory...")
            if not self.run_command(write_cmd):
                self.output_queue.put("Write failed.")
                self.status_var.set("Error: Write failed")
                return

            self.output_queue.put("Done flashing.")
            self.status_var.set("Instalacion terminada.")

            # Start serial reading
            self.output_queue.put(f"Opening serial port {ch340_port} at {self.serial_baud_rate} baud...")
            self.serial_thread = threading.Thread(
                target=self.read_serial, args=(ch340_port,), daemon=True
            )
            self.serial_thread.start()

        except Exception as e:
            self.output_queue.put(f"Error: {str(e)}")
            self.status_var.set("Error occurred")
        finally:
            self.root.after(0, lambda: self.write_button.config(state="normal"))

    def on_closing(self):
        """Handle window close by stopping serial reading and closing the app."""
        self.serial_running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.root.destroy()

if __name__ == "__main__":
    root = ttk.Window()
    app = FirmwareFlasherApp(root)
    root.mainloop()