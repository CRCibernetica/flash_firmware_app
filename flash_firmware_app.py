import tkinter as tk
from tkinter import scrolledtext, messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import os
import threading
import serial
import serial.tools.list_ports
import queue
import re
import time
import esptool
import sys
from io import StringIO

class FirmwareFlasherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Instalador IdeaBoard")
        self.root.geometry("800x600")
        self.style = ttk.Style("litera")

        # Firmware file and baud rates
        self.firmware = "ideaboardfirmware03202025.bin"
        self.flash_baud_rate = 921600  # Integer for esptool API
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
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=BOTH, expand=True)

        header_label = ttk.Label(
            main_frame, text="Instalador IdeaBoard", font=("Helvetica", 20, "bold")
        )
        header_label.pack(pady=(0, 20))

        control_frame = ttk.LabelFrame(main_frame, text="Control", padding=15)
        control_frame.pack(fill=X, pady=10)

        self.flash_button = ttk.Button(
            control_frame,
            text="Instalar Firmware",
            command=self.start_flash,
            style="primary.TButton",
            width=25
        )
        self.flash_button.configure(style="large.primary.TButton")
        self.flash_button.pack(pady=10)

        self.status_var = tk.StringVar(value="Listo")
        status_label = ttk.Label(
            control_frame,
            textvariable=self.status_var,
            font=("Helvetica", 12),
            bootstyle="info"
        )
        status_label.pack(pady=10)

        terminal_frame = ttk.LabelFrame(main_frame, text="Consola", padding=15)
        terminal_frame.pack(fill=BOTH, expand=True, pady=10)

        self.terminal = scrolledtext.ScrolledText(
            terminal_frame,
            height=22,
            font=("Consolas", 12),
            wrap=tk.WORD,
            bg="#2e2e2e",
            fg="#ffffff",
            insertbackground="white"
        )
        self.terminal.pack(fill=BOTH, expand=True)
        self.terminal.config(state="disabled")

        self.style.configure("large.primary.TButton", font=("Helvetica", 14))

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
        self.flash_button.config(state="disabled")
        self.status_var.set("Instalando...")
        self.log("Starting firmware flashing process...")
        self.serial_running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            self.serial_port = None
        threading.Thread(target=self.flash_firmware, daemon=True).start()

    def output_handler(self, message):
        """Handle esptool output by sending it to the queue."""
        if message:
            clean_message = self.strip_ansi_codes(message.strip())
            if clean_message:
                self.output_queue.put(clean_message)

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

        dialog = ttk.Window(self.root, title="Select Serial Port", minsize=(400, 250))
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Select a serial port:", font=("Helvetica", 12)).pack(pady=15)
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

            # Define identifiers for CH340/CH341 chips
            ch340_identifiers = ["CH340", "CH341", "USB Serial"]
            ch340_vid_pid = [(0x1A86, 0x7523), (0x1A86, 0x7522)]

            # Find the CH340 port
            ch340_port = None
            for port in ports:
                self.output_queue.put(f"Port: {port.device}, Description: {port.description}, VID:PID: {port.vid}:{port.pid}")
                if any(identifier in port.description for identifier in ch340_identifiers):
                    ch340_port = port.device
                    break
                if (port.vid, port.pid) in ch340_vid_pid:
                    ch340_port = port.device
                    break

            if ch340_port is None:
                self.output_queue.put("No CH340/USB Serial port found. Prompting for port selection...")
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

            # Redirect esptool output to capture it
            output_buffer = StringIO()
            sys.stdout = output_buffer
            sys.stderr = output_buffer

            try:
                # Erase flash
                self.output_queue.put("Erasing flash memory...")
                esptool.main([
                    "--chip", "esp32",
                    "--port", ch340_port,
                    "erase_flash"
                ])
                output = output_buffer.getvalue()
                for line in output.splitlines():
                    self.output_handler(line)
                output_buffer.truncate(0)
                output_buffer.seek(0)

                # Write firmware
                self.output_queue.put("Writing flash memory...")
                esptool.main([
                    "--chip", "esp32",
                    "--port", ch340_port,
                    "--baud", str(self.flash_baud_rate),
                    "write_flash",
                    "0x0",
                    self.firmware
                ])
                output = output_buffer.getvalue()
                for line in output.splitlines():
                    self.output_handler(line)

                self.output_queue.put("Done flashing.")
                self.status_var.set("Instalacion terminada.")

                # Start serial reading
                self.output_queue.put(f"Opening serial port {ch340_port} at {self.serial_baud_rate} baud...")
                self.serial_thread = threading.Thread(
                    target=self.read_serial, args=(ch340_port,), daemon=True
                )
                self.serial_thread.start()

            except esptool.FatalError as e:
                self.output_queue.put(f"esptool error: {str(e)}")
                self.status_var.set("Error: Flashing failed")
                output = output_buffer.getvalue()
                for line in output.splitlines():
                    self.output_handler(line)
                return
            finally:
                # Restore stdout/stderr
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
                output_buffer.close()

        except Exception as e:
            self.output_queue.put(f"Error: {str(e)}")
            self.status_var.set("Error occurred")
        finally:
            self.root.after(0, lambda: self.flash_button.config(state="normal"))

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