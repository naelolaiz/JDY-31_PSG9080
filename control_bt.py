#!/usr/bin/env python3
import sys
import asyncio
import binascii
from bleak import BleakClient
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTabWidget, QWidget,
                            QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                            QLineEdit, QPushButton, QGroupBox, QSlider, QSpinBox,
                            QDoubleSpinBox, QCheckBox, QGridLayout, QFormLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

# Device Address - Replace with your device's MAC address
DEVICE_ADDRESS = "5C:53:10:DA:D2:DD"
# Characteristic UUIDs
COMMAND_CHARACTERISTIC_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"  # For writing commands
RESPONSE_CHARACTERISTIC_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"  # For receiving responses

# Define waveform options
WAVEFORMS = {
    "Sine": 0,
    "Square": 1,
    "Pulse": 2,
    "Triangle": 3,
    "Slope": 4,
    "CMOS": 5,
    "DC level": 6,
    "Partial sine wave": 7,
    "Half wave": 8,
    "Full wave": 9,
    "Positive ladder wave": 10,
    "Negative ladder wave": 11,
    "Positive trapezoidal wave": 12,
    "Negative trapezoidal wave": 13,
    "Noise wave": 14,
    "Index rise": 15,
    "Index fall": 16,
    "Logarithmic rise": 17,
    "Logarithmic fall": 18,
    "Sinker Pulse": 19,
    "Multi-audio": 20,
    "Lorenz": 21,
}

# Define frequency unit options
FREQ_UNITS = {
    "Hz": 0,
    "kHz": 1,
    "MHz": 2,
    "mHz": 3,
    "μHz": 4,
}

# Command mappings for each parameter type and channel
CMD_MAPPINGS = {
    "output": {1: "w10", 2: "w10"},  # Special case for output
    "waveform": {1: "w11", 2: "w12"},
    "frequency": {1: "w13", 2: "w14"},
    "amplitude": {1: "w15", 2: "w16"},
    "offset": {1: "w17", 2: "w18"},
    "duty": {1: "w19", 2: "w20"},
    "phase": {1: "w21", 2: "w22"},
}

# Read command mappings
READ_CMD_MAPPINGS = {
    "output": "r10",
    "waveform": {1: "r11", 2: "r12"},
    "frequency": {1: "r13", 2: "r14"},
    "amplitude": {1: "r15", 2: "r16"},
    "offset": {1: "r17", 2: "r18"},
    "duty": {1: "r19", 2: "r20"},
    "phase": {1: "r21", 2: "r22"},
}

class BLEWorker(QThread):
    connected = pyqtSignal(bool)
    message_received = pyqtSignal(str)
    notification_received = pyqtSignal(str)
    status_updated = pyqtSignal(dict)

    def __init__(self, address):
        super().__init__()
        self.address = address
        self.client = None
        self.loop = None
        self.running = False
        self.command_queue = asyncio.Queue()
        self.status = {}

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.running = True
        self.loop.run_until_complete(self.run_ble_client())

    def notification_handler(self, sender, data):
        """Handle incoming notifications from the device"""
        try:
            message = data.decode('utf-8').strip()
            self.notification_received.emit(message)

            # Parse status response
            if message.startswith(':r'):
                self.parse_status_response(message)

        except Exception as e:
            self.message_received.emit(f"Error processing notification: {str(e)}")

    def parse_status_response(self, response):
        """Parse a status response and update the status dictionary"""
        try:
            # Basic parsing - can be enhanced for specific commands
            if '=' in response:
                cmd, value = response.split('=', 1)
                cmd = cmd.strip()
                cmd_type = cmd[2:]  # Remove ":r" prefix

                # Parse different response types
                if cmd_type == '10':  # Output status
                    parts = value.split(',')
                    if len(parts) >= 2:
                        self.status['ch1_output'] = parts[0].strip() == '1'
                        self.status['ch2_output'] = parts[1].strip() == '1'

                elif cmd_type == '11':  # Channel 1 waveform
                    self.status['ch1_waveform'] = int(value.strip('.\r\n'))

                elif cmd_type == '12':  # Channel 2 waveform
                    self.status['ch2_waveform'] = int(value.strip('.\r\n'))

                elif cmd_type == '13':  # Channel 1 frequency
                    parts = value.split(',')
                    if len(parts) >= 2:
                        freq_val = int(parts[0].strip()) / 1000.0  # Convert to decimal
                        freq_unit = int(parts[1].strip('.\r\n'))
                        self.status['ch1_frequency'] = freq_val
                        self.status['ch1_freq_unit'] = freq_unit

                elif cmd_type == '14':  # Channel 2 frequency
                    parts = value.split(',')
                    if len(parts) >= 2:
                        freq_val = int(parts[0].strip()) / 1000.0  # Convert to decimal
                        freq_unit = int(parts[1].strip('.\r\n'))
                        self.status['ch2_frequency'] = freq_val
                        self.status['ch2_freq_unit'] = freq_unit

                elif cmd_type == '15':  # Channel 1 amplitude
                    self.status['ch1_amplitude'] = int(value.strip('.\r\n')) / 1000.0  # Convert to volts

                elif cmd_type == '16':  # Channel 2 amplitude
                    self.status['ch2_amplitude'] = int(value.strip('.\r\n')) / 1000.0  # Convert to volts

                elif cmd_type == '17':  # Channel 1 offset
                    offset_val = int(value.strip('.\r\n'))
                    if offset_val == 1000:
                        self.status['ch1_offset'] = 0
                    else:
                        self.status['ch1_offset'] = (offset_val - 1000) / 100.0  # Convert to voltage

                elif cmd_type == '18':  # Channel 2 offset
                    offset_val = int(value.strip('.\r\n'))
                    if offset_val == 1000:
                        self.status['ch2_offset'] = 0
                    else:
                        self.status['ch2_offset'] = (offset_val - 1000) / 100.0  # Convert to voltage

                elif cmd_type == '19':  # Channel 1 duty cycle
                    self.status['ch1_duty'] = int(value.strip('.\r\n')) / 100.0  # Convert to percentage

                elif cmd_type == '20':  # Channel 2 duty cycle
                    self.status['ch2_duty'] = int(value.strip('.\r\n')) / 100.0  # Convert to percentage

                elif cmd_type == '21':  # Channel 1 phase
                    self.status['ch1_phase'] = int(value.strip('.\r\n')) / 100.0  # Convert to degrees

                elif cmd_type == '22':  # Channel 2 phase
                    self.status['ch2_phase'] = int(value.strip('.\r\n')) / 100.0  # Convert to degrees

                # Emit signal with updated status
                self.status_updated.emit(self.status)

        except Exception as e:
            self.message_received.emit(f"Error parsing status response: {str(e)}")

    async def run_ble_client(self):
        try:
            self.client = BleakClient(self.address)
            await self.client.connect()
            self.connected.emit(True)
            self.message_received.emit(f"Connected to {self.address}")

            # Enable notifications for response characteristic
            await self.client.start_notify(RESPONSE_CHARACTERISTIC_UUID, self.notification_handler)
            self.message_received.emit("Notifications enabled")

            # Query current device status
            await self.query_device_status()

            # Process commands from the queue
            while self.running:
                try:
                    command = await asyncio.wait_for(self.command_queue.get(), timeout=0.1)
                    await self.send_command(command)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    self.message_received.emit(f"Error processing command: {str(e)}")

        except Exception as e:
            self.message_received.emit(f"Connection error: {str(e)}")
            self.connected.emit(False)
        finally:
            if self.client and self.client.is_connected:
                try:
                    await self.client.stop_notify(RESPONSE_CHARACTERISTIC_UUID)
                except:
                    pass
                await self.client.disconnect()
            self.connected.emit(False)
            self.message_received.emit("Disconnected")

    async def query_device_status(self):
        """Query the device for its current settings"""
        self.message_received.emit("Querying device status...")

        # List of read commands to send
        read_commands = [
            ":r10=0.",  # Output status
            ":r11=0.",  # Channel 1 waveform
            ":r12=0.",  # Channel 2 waveform
            ":r13=0.",  # Channel 1 frequency
            ":r14=0.",  # Channel 2 frequency
            ":r15=0.",  # Channel 1 amplitude
            ":r16=0.",  # Channel 2 amplitude
            ":r17=0.",  # Channel 1 offset
            ":r18=0.",  # Channel 2 offset
            ":r19=0.",  # Channel 1 duty cycle
            ":r20=0.",  # Channel 2 duty cycle
            ":r21=0.",  # Channel 1 phase
            ":r22=0.",  # Channel 2 phase
        ]

        for cmd in read_commands:
            await self.send_command(cmd)
            # Give the device time to respond
            await asyncio.sleep(0.2)

    async def send_command(self, command):
        if not self.client or not self.client.is_connected:
            self.message_received.emit("Not connected. Cannot send command.")
            return

        try:
            # Convert command string to bytes, adding CR+LF
            if not command.endswith('\r\n'):
                command += '\r\n'

            command_bytes = command.encode('utf-8')
            self.message_received.emit(f"Sending: {command}")

            await self.client.write_gatt_char(COMMAND_CHARACTERISTIC_UUID, command_bytes)
            self.message_received.emit(f"Command sent successfully")

            # Wait briefly for notification response
            await asyncio.sleep(0.1)

        except Exception as e:
            self.message_received.emit(f"Error sending command: {str(e)}")

    def queue_command(self, command):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.command_queue.put(command), self.loop)

    def stop(self):
        self.running = False
        self.wait()

    def query_specific_setting(self, read_command):
        """Queue a specific read command"""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.command_queue.put(read_command), self.loop)


class SignalGeneratorUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ble_worker = BLEWorker(DEVICE_ADDRESS)
        self.ble_worker.connected.connect(self.update_connection_status)
        self.ble_worker.message_received.connect(self.update_message_log)
        self.ble_worker.notification_received.connect(self.update_notification_log)
        self.ble_worker.status_updated.connect(self.update_ui_from_status)
        self.ble_worker.start()

        self.channel_controls = {}  # Store controls by channel for easy access

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Signal Generator Control')
        self.setGeometry(100, 100, 800, 600)

        # Main layout
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)

        # Connection status
        connection_layout = QHBoxLayout()
        self.connection_status = QLabel("Disconnected")
        connection_layout.addWidget(QLabel("Status:"))
        connection_layout.addWidget(self.connection_status)
        connection_layout.addStretch(1)

        # Manual command input
        manual_cmd_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Enter command (e.g., :w11=0.)")
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_manual_command)
        manual_cmd_layout.addWidget(self.cmd_input)
        manual_cmd_layout.addWidget(send_btn)

        # Message logs
        logs_group = QGroupBox("Communication Log")
        logs_layout = QVBoxLayout(logs_group)

        # Command log
        cmd_log_layout = QHBoxLayout()
        cmd_log_layout.addWidget(QLabel("Commands:"))
        self.message_log = QLineEdit()
        self.message_log.setReadOnly(True)
        cmd_log_layout.addWidget(self.message_log)

        # Notification log
        notify_log_layout = QHBoxLayout()
        notify_log_layout.addWidget(QLabel("Response:"))
        self.notification_log = QLineEdit()
        self.notification_log.setReadOnly(True)
        notify_log_layout.addWidget(self.notification_log)

        logs_layout.addLayout(cmd_log_layout)
        logs_layout.addLayout(notify_log_layout)

        # Create tabs for different channels
        tab_widget = QTabWidget()

        # Initialize each channel
        self.channel_controls[1] = {}  # Controls for channel 1
        self.channel_controls[2] = {}  # Controls for channel 2

        # Create each channel tab
        for channel in [1, 2]:
            tab = self.create_channel_tab(channel)
            tab_widget.addTab(tab, f"Channel {channel}")

        # Refresh button
        refresh_btn = QPushButton("Refresh Device Status")
        refresh_btn.clicked.connect(self.refresh_device_status)

        # Add widgets to main layout
        main_layout.addLayout(connection_layout)
        main_layout.addLayout(manual_cmd_layout)
        main_layout.addWidget(logs_group)
        main_layout.addWidget(refresh_btn)
        main_layout.addWidget(tab_widget)

        self.setCentralWidget(main_widget)

    def create_channel_tab(self, channel):
        """Create a tab for controlling a specific channel"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Waveform control
        waveform_group = QGroupBox("Waveform")
        waveform_layout = QFormLayout(waveform_group)

        # On/Off control
        enable = QCheckBox("Enable Output")
        enable.stateChanged.connect(lambda state, ch=channel: self.update_parameter(ch, "output", state))
        waveform_layout.addRow("Output:", enable)
        self.channel_controls[channel]["enable"] = enable

        # Waveform type
        waveform = QComboBox()
        for wave_name in WAVEFORMS:
            waveform.addItem(wave_name)
        waveform.currentIndexChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "waveform"))
        waveform_layout.addRow("Type:", waveform)
        self.channel_controls[channel]["waveform"] = waveform

        # Frequency
        freq_layout = QHBoxLayout()
        frequency = QDoubleSpinBox()
        frequency.setRange(0, 1000000)
        frequency.setDecimals(3)
        frequency.setValue(1000)
        frequency.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "frequency"))

        freq_unit = QComboBox()
        for unit in FREQ_UNITS:
            freq_unit.addItem(unit)
        freq_unit.currentIndexChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "frequency"))

        freq_layout.addWidget(frequency)
        freq_layout.addWidget(freq_unit)
        waveform_layout.addRow("Frequency:", freq_layout)
        self.channel_controls[channel]["frequency"] = frequency
        self.channel_controls[channel]["freq_unit"] = freq_unit

        # Amplitude
        amplitude = QDoubleSpinBox()
        amplitude.setRange(0, 20)
        amplitude.setDecimals(3)
        amplitude.setValue(5)
        amplitude.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "amplitude"))
        waveform_layout.addRow("Amplitude (Vpp):", amplitude)
        self.channel_controls[channel]["amplitude"] = amplitude

        # Offset
        offset = QDoubleSpinBox()
        offset.setRange(-10, 10)
        offset.setDecimals(2)
        offset.setValue(0)
        offset.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "offset"))
        waveform_layout.addRow("Offset (V):", offset)
        self.channel_controls[channel]["offset"] = offset

        # Duty Cycle (for square, pulse)
        duty = QDoubleSpinBox()
        duty.setRange(0, 100)
        duty.setDecimals(2)
        duty.setValue(50)
        duty.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "duty"))
        waveform_layout.addRow("Duty Cycle (%):", duty)
        self.channel_controls[channel]["duty"] = duty

        # Phase
        phase = QDoubleSpinBox()
        phase.setRange(0, 360)
        phase.setDecimals(2)
        phase.setValue(0)
        phase.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "phase"))
        waveform_layout.addRow("Phase (°):", phase)
        self.channel_controls[channel]["phase"] = phase

        # Apply all button
        apply_all_btn = QPushButton("Apply All Settings")
        apply_all_btn.clicked.connect(lambda _, ch=channel: self.apply_all_settings(ch))

        layout.addWidget(waveform_group)
        layout.addWidget(apply_all_btn)
        layout.addStretch(1)

        return tab

    def refresh_device_status(self):
        """Request a refresh of all device settings"""
        self.message_log.setText("Refreshing device status...")
        # Queue read commands for all parameters
        self.ble_worker.queue_command(":r10=0.")  # Output status
        self.ble_worker.queue_command(":r11=0.")  # Channel 1 waveform
        self.ble_worker.queue_command(":r12=0.")  # Channel 2 waveform
        self.ble_worker.queue_command(":r13=0.")  # Channel 1 frequency
        self.ble_worker.queue_command(":r14=0.")  # Channel 2 frequency
        self.ble_worker.queue_command(":r15=0.")  # Channel 1 amplitude
        self.ble_worker.queue_command(":r16=0.")  # Channel 2 amplitude
        self.ble_worker.queue_command(":r17=0.")  # Channel 1 offset
        self.ble_worker.queue_command(":r18=0.")  # Channel 2 offset
        self.ble_worker.queue_command(":r19=0.")  # Channel 1 duty cycle
        self.ble_worker.queue_command(":r20=0.")  # Channel 2 duty cycle
        self.ble_worker.queue_command(":r21=0.")  # Channel 1 phase
        self.ble_worker.queue_command(":r22=0.")  # Channel 2 phase

    def send_manual_command(self):
        """Send a manually entered command"""
        command = self.cmd_input.text()
        if command:
            self.ble_worker.queue_command(command)
            self.cmd_input.clear()

    def update_parameter(self, channel, param_type, state=None):
        """Update a parameter for the specified channel"""
        if param_type == "output":
            # Handle the special case for output which needs both channels
            ch1_state = "1" if (channel == 1 and state == Qt.Checked) or \
                           (channel == 2 and self.channel_controls[1]["enable"].isChecked()) else "0"
            ch2_state = "1" if (channel == 2 and state == Qt.Checked) or \
                           (channel == 1 and self.channel_controls[2]["enable"].isChecked()) else "0"
            self.ble_worker.queue_command(f":w10={ch1_state},{ch2_state}.")
            return

        # Handle other parameters
        if param_type == "waveform":
            waveform_idx = WAVEFORMS[self.channel_controls[channel]["waveform"].currentText()]
            value = f"{waveform_idx}."

        elif param_type == "frequency":
            value = self.channel_controls[channel]["frequency"].value()
            unit_idx = FREQ_UNITS[self.channel_controls[channel]["freq_unit"].currentText()]
            value = f"{int(value*1000)},{unit_idx}."

        elif param_type == "amplitude":
            value = self.channel_controls[channel]["amplitude"].value()
            value = f"{int(value*1000)}."

        elif param_type == "offset":
            value = self.channel_controls[channel]["offset"].value()
            if value == 0:
                offset_value = 1000
            else:
                offset_value = int(1000 + value * 100)
            value = f"{offset_value}."

        elif param_type == "duty":
            value = self.channel_controls[channel]["duty"].value()
            value = f"{int(value*100)}."

        elif param_type == "phase":
            value = self.channel_controls[channel]["phase"].value()
            value = f"{int(value*100)}."

        # Get the command for this parameter and channel
        cmd = CMD_MAPPINGS[param_type][channel]
        self.ble_worker.queue_command(f":{cmd}={value}")

    def apply_all_settings(self, channel):
        """Apply all settings for the specified channel"""
        for param in ["waveform", "frequency", "amplitude", "offset", "duty", "phase"]:
            self.update_parameter(channel, param)
        # Update output state last
        self.update_parameter(channel, "output", self.channel_controls[channel]["enable"].checkState())

    @pyqtSlot(bool)
    def update_connection_status(self, connected):
        """Update connection status display"""
        if connected:
            self.connection_status.setText("Connected")
            self.connection_status.setStyleSheet("color: green")
        else:
            self.connection_status.setText("Disconnected")
            self.connection_status.setStyleSheet("color: red")

    @pyqtSlot(str)
    def update_message_log(self, message):
        """Update command log display"""
        self.message_log.setText(message)

    @pyqtSlot(str)
    def update_notification_log(self, message):
        """Update notification log display"""
        self.notification_log.setText(message)

    @pyqtSlot(dict)
    def update_ui_from_status(self, status):
        """Update UI controls based on received device status"""
        # Update UI elements with received status values
        if 'ch1_output' in status:
            self.channel_controls[1]["enable"].setChecked(status['ch1_output'])

        if 'ch2_output' in status:
            self.channel_controls[2]["enable"].setChecked(status['ch2_output'])

        for channel in [1, 2]:
            ch_prefix = f"ch{channel}_"

            if f'{ch_prefix}waveform' in status:
                waveform_value = status[f'{ch_prefix}waveform']
                # Find the corresponding waveform name
                for name, value in WAVEFORMS.items():
                    if value == waveform_value:
                        index = self.channel_controls[channel]["waveform"].findText(name)
                        if index >= 0:
                            self.channel_controls[channel]["waveform"].setCurrentIndex(index)
                        break

            if f'{ch_prefix}frequency' in status and f'{ch_prefix}freq_unit' in status:
                self.channel_controls[channel]["frequency"].setValue(status[f'{ch_prefix}frequency'])
                self.channel_controls[channel]["freq_unit"].setCurrentIndex(status[f'{ch_prefix}freq_unit'])

            if f'{ch_prefix}amplitude' in status:
                self.channel_controls[channel]["amplitude"].setValue(status[f'{ch_prefix}amplitude'])

            if f'{ch_prefix}offset' in status:
                self.channel_controls[channel]["offset"].setValue(status[f'{ch_prefix}offset'])

            if f'{ch_prefix}duty' in status:
                self.channel_controls[channel]["duty"].setValue(status[f'{ch_prefix}duty'])

            if f'{ch_prefix}phase' in status:
                self.channel_controls[channel]["phase"].setValue(status[f'{ch_prefix}phase'])

    def closeEvent(self, event):
        # Clean up BLE worker thread
        self.ble_worker.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = SignalGeneratorUI()
    ui.show()
    sys.exit(app.exec_())
