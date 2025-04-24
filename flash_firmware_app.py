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
        # Known Vendor ID and Product ID for CH340/CH341 (e.g., 1a86:7523)
        ch340_vid_pid = [(0x1A86, 0x7523), (0x1A86, 0x7522)]

        # Find the CH340 port
        ch340_port = None
        for port in ports:
            self.output_queue.put(f"Port: {port.device}, Description: {port.description}, VID:PID: {port.vid}:{port.pid}")
            # Check description for CH340/CH341 or USB Serial
            if any(identifier in port.description for identifier in ch340_identifiers):
                ch340_port = port.device
                break
            # Check VID:PID for CH340/CH341
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
        self.root.after(0, lambda: self.flash_button.config(state="normal"))