// Audio device settings page
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../controls"

ScrollView {
    id: root
    clip: true
    contentWidth: availableWidth
    ScrollBar.vertical.policy: ScrollBar.AlwaysOn
    // the always-on bar is an overlay and reserves no space; without this
    // the right-hand controls sit underneath it
    rightPadding: 14

    // Test state
    property bool inputTesting: false
    property bool outputTesting: false

    // Status log
    property var statusLogs: []

    function addLog(message) {
        var timestamp = new Date().toLocaleTimeString(Qt.locale(), "HH:mm:ss")
        statusLogs = [...statusLogs, "[" + timestamp + "] " + message]
        if (statusLogs.length > 20) {
            statusLogs = statusLogs.slice(-20)
        }
    }

    // Load the device list on init
    Component.onCompleted: {
        if (settingsModel) {
            inputCombo.model = settingsModel.getInputDevices()
            outputCombo.model = settingsModel.getOutputDevices()
            // resync currentIndex after the model is set
            inputCombo.currentIndex = settingsModel.selectedInputIndex
            outputCombo.currentIndex = settingsModel.selectedOutputIndex
            addLog("Device list loaded")
        }
    }

    Connections {
        target: settingsModel
        function onDevicesChanged() {
            if (settingsModel) {
                inputCombo.model = settingsModel.getInputDevices()
                outputCombo.model = settingsModel.getOutputDevices()
                // resync currentIndex after the model is set
                inputCombo.currentIndex = settingsModel.selectedInputIndex
                outputCombo.currentIndex = settingsModel.selectedOutputIndex
                addLog("Device list refreshed")
            }
        }
        function onTestComplete(type, success) {
            if (type === "input") {
                root.inputTesting = false
            } else if (type === "output") {
                root.outputTesting = false
            }
        }
        function onStatusMessage(message) {
            addLog(message)
        }
    }

    ColumnLayout {
        width: root.availableWidth
        spacing: Theme.spacingLg

        // Page title
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Audio Devices"
                font.pixelSize: Theme.fontSizeXl
                font.weight: Font.DemiBold
                color: Theme.textPrimary
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "Refresh Devices"
                Layout.preferredHeight: 32

                background: Rectangle {
                    color: parent.pressed ? Theme.divider : (parent.hovered ? Theme.backgroundSecondary : Theme.backgroundHover)
                    radius: Theme.radiusSm
                }

                contentItem: Text {
                    text: parent.text
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }

                onClicked: if (settingsModel) settingsModel.refreshDevices()
            }
        }

        // Input device
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Input Device (Microphone)"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                XComboBox {
                    id: inputCombo
                    Layout.fillWidth: true
                    currentIndex: settingsModel ? settingsModel.selectedInputIndex : 0
                    onActivated: function(index) {
                        if (settingsModel) settingsModel.selectedInputIndex = index
                    }
                    font.pixelSize: Theme.fontSizeSm
                }

                Button {
                    text: root.inputTesting ? "Testing..." : "Test"
                    enabled: !root.inputTesting
                    Layout.preferredWidth: 80
                    Layout.preferredHeight: 32

                    background: Rectangle {
                        color: parent.enabled ? (parent.pressed ? Theme.primaryPressed : (parent.hovered ? Theme.primaryHover : Theme.primary)) : Theme.textPlaceholder
                        radius: Theme.radiusSm
                    }

                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: "white"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }

                    onClicked: {
                        root.inputTesting = true
                        if (settingsModel) settingsModel.testInputDevice()
                    }
                }
            }

            // Device info
            Rectangle {
                Layout.fillWidth: true
                height: 36
                color: Theme.backgroundSecondary
                radius: Theme.radiusSm

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.spacingMd
                    anchors.verticalCenter: parent.verticalCenter
                    text: settingsModel ? settingsModel.inputDeviceInfo : ""
                    font.pixelSize: Theme.fontSizeXs
                    color: Theme.textPlaceholder
                }
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Output device
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Output Device (Speaker)"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                XComboBox {
                    id: outputCombo
                    Layout.fillWidth: true
                    currentIndex: settingsModel ? settingsModel.selectedOutputIndex : 0
                    onActivated: function(index) {
                        if (settingsModel) settingsModel.selectedOutputIndex = index
                    }
                    font.pixelSize: Theme.fontSizeSm
                }

                Button {
                    text: root.outputTesting ? "Testing..." : "Test"
                    enabled: !root.outputTesting
                    Layout.preferredWidth: 80
                    Layout.preferredHeight: 32

                    background: Rectangle {
                        color: parent.enabled ? (parent.pressed ? Theme.primaryPressed : (parent.hovered ? Theme.primaryHover : Theme.primary)) : Theme.textPlaceholder
                        radius: Theme.radiusSm
                    }

                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: "white"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }

                    onClicked: {
                        root.outputTesting = true
                        if (settingsModel) settingsModel.testOutputDevice()
                    }
                }
            }

            // Device info
            Rectangle {
                Layout.fillWidth: true
                height: 36
                color: Theme.backgroundSecondary
                radius: Theme.radiusSm

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.spacingMd
                    anchors.verticalCenter: parent.verticalCenter
                    text: settingsModel ? settingsModel.outputDeviceInfo : ""
                    font.pixelSize: Theme.fontSizeXs
                    color: Theme.textPlaceholder
                }
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Opus output sample rate
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Opus Output Sample Rate"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                XComboBox {
                    id: sampleRateCombo
                    Layout.fillWidth: true
                    model: ["24000 Hz (official server)", "16000 Hz (third-party server)"]
                    currentIndex: settingsModel ? (settingsModel.opusOutputSampleRate === 24000 ? 0 : 1) : 0
                    onActivated: function(index) {
                        if (settingsModel) {
                            settingsModel.opusOutputSampleRate = (index === 0) ? 24000 : 16000
                            addLog("Opus output sample rate set to " + (index === 0 ? "24000" : "16000") + " Hz")
                        }
                    }
                    font.pixelSize: Theme.fontSizeSm
                }
            }

            // Hint
            Rectangle {
                Layout.fillWidth: true
                height: 36
                color: Theme.backgroundSecondary
                radius: Theme.radiusSm

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.spacingMd
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Official servers use 24kHz; third-party servers usually use 16kHz"
                    font.pixelSize: Theme.fontSizeXs
                    color: Theme.textPlaceholder
                }
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Audio frame length
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Audio Frame Length"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                XComboBox {
                    id: frameDurationCombo
                    Layout.fillWidth: true
                    model: ["20 ms (low latency)", "40 ms (balanced)", "60 ms (low CPU)"]
                    currentIndex: {
                        if (!settingsModel) return 0
                        var duration = settingsModel.frameDuration
                        if (duration === 20) return 0
                        if (duration === 40) return 1
                        if (duration === 60) return 2
                        return 0
                    }
                    onActivated: function(index) {
                        if (settingsModel) {
                            var durations = [20, 40, 60]
                            settingsModel.frameDuration = durations[index]
                            addLog("Audio frame length set to " + durations[index] + " ms")
                        }
                    }
                    font.pixelSize: Theme.fontSizeSm
                }
            }

            // Hint
            Rectangle {
                Layout.fillWidth: true
                height: 36
                color: Theme.backgroundSecondary
                radius: Theme.radiusSm

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.spacingMd
                    anchors.verticalCenter: parent.verticalCenter
                    text: "20ms = low latency, high CPU; 60ms = high latency, low CPU (good for Raspberry Pi)"
                    font.pixelSize: Theme.fontSizeXs
                    color: Theme.textPlaceholder
                }
            }
        }

        // Hint text
        Text {
            Layout.fillWidth: true
            text: "Click Test to verify the device works. The input test records 3 seconds of audio; the output test plays a 440Hz tone."
            font.pixelSize: Theme.fontSizeSm
            color: Theme.textPlaceholder
            wrapMode: Text.WordWrap
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Status log section
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            RowLayout {
                Layout.fillWidth: true

                Text {
                    text: "Status Log"
                    font.pixelSize: Theme.fontSizeMd
                    font.weight: Font.Medium
                    color: Theme.textSecondary
                }

                Item { Layout.fillWidth: true }

                Button {
                    text: "Clear Log"
                    Layout.preferredHeight: 28

                    background: Rectangle {
                        color: parent.pressed ? Theme.divider : (parent.hovered ? Theme.backgroundSecondary : Theme.backgroundHover)
                        radius: Theme.radiusSm
                    }

                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeXs
                        color: Theme.textSecondary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }

                    onClicked: {
                        root.statusLogs = []
                        addLog("Log cleared")
                    }
                }
            }

            // Log display area
            Rectangle {
                Layout.fillWidth: true
                height: 120
                color: Theme.textPrimary
                radius: Theme.radiusSm

                ScrollView {
                    id: logScrollView
                    anchors.fill: parent
                    anchors.margins: Theme.spacingSm
                    clip: true

                    TextArea {
                        id: logText
                        readOnly: true
                        text: root.statusLogs.join("\n")
                        color: Theme.success
                        font.pixelSize: Theme.fontSizeXs
                        wrapMode: Text.NoWrap
                        background: null
                        selectByMouse: true

                        onTextChanged: {
                            logScrollView.ScrollBar.vertical.position = 1.0 - logScrollView.ScrollBar.vertical.size
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
