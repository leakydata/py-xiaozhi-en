// The control panel
import QtQuick
import QtQuick.Layouts
import "../theme"
import "../controls"

Rectangle {
    id: root

    color: Theme.backgroundSecondary

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingMd
        spacing: Theme.spacingMd

        // the input area
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            XTextField {
                id: inputField
                Layout.fillWidth: true
                placeholderText: "Type a message..."

                Keys.onReturnPressed: sendText()
            }

            XButton {
                text: "Send"
                onClicked: sendText()
            }
        }

        // the control buttons
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            // switch between manual and auto mode
            XButton {
                Layout.fillWidth: true
                text: mainModel.autoMode ? "Switch to Manual" : "Switch to Auto"
                variant: "secondary"
                onClicked: eventBridge.onAutoToggle()
            }

            // the talk button (manual mode)
            XButton {
                Layout.fillWidth: true
                text: mainModel.buttonText
                visible: !mainModel.autoMode
                onPressed: eventBridge.onButtonPress()
                onReleased: eventBridge.onButtonRelease()
            }

            // the interrupt button
            XButton {
                Layout.preferredWidth: 80
                text: "Abort"
                variant: "secondary"
                onClicked: eventBridge.onAbort()
            }
        }
    }

    function sendText() {
        let text = inputField.text.trim()
        if (text.length > 0) {
            eventBridge.onSendText(text)
            inputField.text = ""
        }
    }
}
