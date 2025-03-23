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
                
                elif cmd_type == '13':  # Channel 1 frequency
                    parts = value.split(',')
                    if len(parts) >= 2:
                        freq_val = int(parts[0].strip()) / 1000.0  # Convert to decimal
                        freq_unit = int(parts[1].strip('.\r\n'))
                        self.status['ch1_frequency'] = freq_val
                        self.status['ch1_freq_unit'] = freq_unit
                
                elif cmd_type == '15':  # Channel 1 amplitude
                    self.status['ch1_amplitude'] = int(value.strip('.\r\n')) / 1000.0  # Convert to volts
                
                elif cmd_type == '17':  # Channel 1 offset
                    offset_val = int(value.strip('.\r\n'))
                    if offset_val == 1000:
                        self.status['ch1_offset'] = 0
                    else:
                        self.status['ch1_offset'] = (offset_val - 1000) / 100.0  # Convert to voltage
                
                elif cmd_type == '19':  # Channel 1 duty cycle
                    self.status['ch1_duty'] = int(value.strip('.\r\n')) / 100.0  # Convert to percentage
                
                elif cmd_type == '21':  # Channel 1 phase
                    self.status['ch1_phase'] = int(value.strip('.\r\n')) / 100.0  # Convert to degrees
                
                # Update status for other responses similarly...
                
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
            ":r13=0.",  # Channel 1 frequency
            ":r15=0.",  # Channel 1 amplitude
            ":r17=0.",  # Channel 1 offset
            ":r19=0.",  # Channel 1 duty cycle
            ":r21=0.",  # Channel 1 phase
            # Add more commands for Channel 2 if needed
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
        
        # Create tabs for different functions
        tab_widget = QTabWidget()
        
        # Channel 1 tab
        ch1_tab = QWidget()
        ch1_layout = QVBoxLayout(ch1_tab)
        
        # Waveform control
        waveform_group = QGroupBox("Waveform")
        waveform_layout = QFormLayout(waveform_group)
        
        # On/Off control
        self.ch1_enable = QCheckBox("Enable Output")
        self.ch1_enable.stateChanged.connect(self.update_ch1_output)
        waveform_layout.addRow("Output:", self.ch1_enable)
        
        # Waveform type
        self.ch1_waveform = QComboBox()
        for waveform in WAVEFORMS:
            self.ch1_waveform.addItem(waveform)
        self.ch1_waveform.currentIndexChanged.connect(self.update_ch1_waveform)
        waveform_layout.addRow("Type:", self.ch1_waveform)
        
        # Frequency
        freq_layout = QHBoxLayout()
        self.ch1_frequency = QDoubleSpinBox()
        self.ch1_frequency.setRange(0, 1000000)
        self.ch1_frequency.setDecimals(3)
        self.ch1_frequency.setValue(1000)
        self.ch1_frequency.valueChanged.connect(self.update_ch1_frequency)
        
        self.ch1_freq_unit = QComboBox()
        for unit in FREQ_UNITS:
            self.ch1_freq_unit.addItem(unit)
        self.ch1_freq_unit.currentIndexChanged.connect(self.update_ch1_frequency)
        
        freq_layout.addWidget(self.ch1_frequency)
        freq_layout.addWidget(self.ch1_freq_unit)
        waveform_layout.addRow("Frequency:", freq_layout)
        
        # Amplitude
        self.ch1_amplitude = QDoubleSpinBox()
        self.ch1_amplitude.setRange(0, 20)
        self.ch1_amplitude.setDecimals(3)
        self.ch1_amplitude.setValue(5)
        self.ch1_amplitude.valueChanged.connect(self.update_ch1_amplitude)
        waveform_layout.addRow("Amplitude (Vpp):", self.ch1_amplitude)
        
        # Offset
        self.ch1_offset = QDoubleSpinBox()
        self.ch1_offset.setRange(-10, 10)
        self.ch1_offset.setDecimals(2)
        self.ch1_offset.setValue(0)
        self.ch1_offset.valueChanged.connect(self.update_ch1_offset)
        waveform_layout.addRow("Offset (V):", self.ch1_offset)
        
        # Duty Cycle (for square, pulse)
        self.ch1_duty = QDoubleSpinBox()
        self.ch1_duty.setRange(0, 100)
        self.ch1_duty.setDecimals(2)
        self.ch1_duty.setValue(50)
        self.ch1_duty.valueChanged.connect(self.update_ch1_duty)
        waveform_layout.addRow("Duty Cycle (%):", self.ch1_duty)
        
        # Phase
        self.ch1_phase = QDoubleSpinBox()
        self.ch1_phase.setRange(0, 360)
        self.ch1_phase.setDecimals(2)
        self.ch1_phase.setValue(0)
        self.ch1_phase.valueChanged.connect(self.update_ch1_phase)
        waveform_layout.addRow("Phase (°):", self.ch1_phase)
        
        # Apply all button
        apply_all_btn = QPushButton("Apply All Settings")
        apply_all_btn.clicked.connect(self.apply_all_ch1_settings)
        
        ch1_layout.addWidget(waveform_group)
        ch1_layout.addWidget(apply_all_btn)
        ch1_layout.addStretch(1)
        
        # Channel 2 tab (similar structure to Channel 1)
        ch2_tab = QWidget()
        
        # Add tabs
        tab_widget.addTab(ch1_tab, "Channel 1")
        tab_widget.addTab(ch2_tab, "Channel 2")
        
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
    
    def refresh_device_status(self):
        """Request a refresh of all device settings"""
        self.message_log.setText("Refreshing device status...")
        # Queue read commands for all parameters
        self.ble_worker.queue_command(":r10=0.")  # Output status
        self.ble_worker.queue_command(":r11=0.")  # Channel 1 waveform
        self.ble_worker.queue_command(":r13=0.")  # Channel 1 frequency
        self.ble_worker.queue_command(":r15=0.")  # Channel 1 amplitude
        self.ble_worker.queue_command(":r17=0.")  # Channel 1 offset
        self.ble_worker.queue_command(":r19=0.")  # Channel 1 duty cycle
        self.ble_worker.queue_command(":r21=0.")  # Channel 1 phase
    
    def send_manual_command(self):
        command = self.cmd_input.text()
        if command:
            self.ble_worker.queue_command(command)
            self.cmd_input.clear()
    
    @pyqtSlot(bool)
    def update_connection_status(self, connected):
        if connected:
            self.connection_status.setText("Connected")
            self.connection_status.setStyleSheet("color: green")
        else:
            self.connection_status.setText("Disconnected")
            self.connection_status.setStyleSheet("color: red")
    
    @pyqtSlot(str)
    def update_message_log(self, message):
        self.message_log.setText(message)
    
    @pyqtSlot(str)
    def update_notification_log(self, message):
        self.notification_log.setText(message)
    
    @pyqtSlot(dict)
    def update_ui_from_status(self, status):
        """Update UI controls based on received device status"""
        # Update UI elements with received status values
        if 'ch1_output' in status:
            self.ch1_enable.setChecked(status['ch1_output'])
            
        if 'ch1_waveform' in status:
            waveform_value = status['ch1_waveform']
            # Find the corresponding waveform name
            for name, value in WAVEFORMS.items():
                if value == waveform_value:
                    index = self.ch1_waveform.findText(name)
                    if index >= 0:
                        self.ch1_waveform.setCurrentIndex(index)
                    break
        
        if 'ch1_frequency' in status and 'ch1_freq_unit' in status:
            self.ch1_frequency.setValue(status['ch1_frequency'])
            self.ch1_freq_unit.setCurrentIndex(status['ch1_freq_unit'])
            
        if 'ch1_amplitude' in status:
            self.ch1_amplitude.setValue(status['ch1_amplitude'])
            
        if 'ch1_offset' in status:
            self.ch1_offset.setValue(status['ch1_offset'])
            
        if 'ch1_duty' in status:
            self.ch1_duty.setValue(status['ch1_duty'])
            
        if 'ch1_phase' in status:
            self.ch1_phase.setValue(status['ch1_phase'])
        
    def update_ch1_output(self, state):
        if state == Qt.Checked:
            self.ble_worker.queue_command(":w10=1,0.")
        else:
            self.ble_worker.queue_command(":w10=0,0.")
            
    def update_ch1_waveform(self):
        waveform_idx = WAVEFORMS[self.ch1_waveform.currentText()]
        self.ble_worker.queue_command(f":w11={waveform_idx}.")
        
    def update_ch1_frequency(self):
        value = self.ch1_frequency.value()
        unit_idx = FREQ_UNITS[self.ch1_freq_unit.currentText()]
        self.ble_worker.queue_command(f":w13={int(value*1000)},{unit_idx}.")
        
    def update_ch1_amplitude(self):
        value = self.ch1_amplitude.value()
        # Convert to millivolts (multiply by 1000)
        self.ble_worker.queue_command(f":w15={int(value*1000)}.")
        
    def update_ch1_offset(self):
        value = self.ch1_offset.value()
        # Convert to offset format per the documentation
        if value == 0:
            offset_value = 1000
        else:
            # Scale to the correct range (1 to 2499 for -9.99V to +15V)
            offset_value = int(1000 + value * 100)
        self.ble_worker.queue_command(f":w17={offset_value}.")
        
    def update_ch1_duty(self):
        value = self.ch1_duty.value()
        # Multiply by 100 to get the format expected by the device
        self.ble_worker.queue_command(f":w19={int(value*100)}.")
        
    def update_ch1_phase(self):
        value = self.ch1_phase.value()
        # Multiply by 100 to get the format expected by the device
        self.ble_worker.queue_command(f":w21={int(value*100)}.")
        
    def apply_all_ch1_settings(self):
        # Send all Channel 1 settings in sequence
        self.update_ch1_waveform()
        self.update_ch1_frequency()
        self.update_ch1_amplitude()
        self.update_ch1_offset()
        self.update_ch1_duty()
        self.update_ch1_phase()
        self.update_ch1_output(self.ch1_enable.checkState())
        
    def closeEvent(self, event):
        # Clean up BLE worker thread
        self.ble_worker.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = SignalGeneratorUI()
    ui.show()
    sys.exit(app.exec_())
