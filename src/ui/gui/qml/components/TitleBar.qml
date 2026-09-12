// A custom title bar that adapts to the platform
import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root

    height: Theme.titleBarHeight
    color: Theme.backgroundSecondary  // background colour

    property string title: ""
    property bool showMinimize: true
    property bool showMaximize: false  // the maximise button is hidden by default
    property bool showClose: true

    signal minimizeClicked()
    signal maximizeClicked()
    signal closeClicked()

    // the draggable area
    MouseArea {
        id: dragArea
        anchors.fill: parent
        // macOS keeps the left clear for the buttons; Windows and Linux keep the right clear
        anchors.leftMargin: Theme.titleButtonsOnLeft ? (macButtons.width + Theme.spacingLg) : 0
        anchors.rightMargin: Theme.titleButtonsOnLeft ? 0 : (winButtons.width + Theme.spacingMd)

        onPressed: {
            // the native drag API, which works everywhere including Linux under Wayland
            let win = Window.window
            if (win) {
                win.startSystemMove()
            }
        }

        onDoubleClicked: {
            let win = Window.window
            if (win) {
                // double-click goes fullscreen on macOS, and maximises on Windows and Linux
                if (Theme.titleButtonsOnLeft) {
                    if (win.visibility === Window.FullScreen) {
                        win.showNormal()
                    } else {
                        win.showFullScreen()
                    }
                } else {
                    if (win.visibility === Window.Maximized) {
                        win.showNormal()
                    } else {
                        win.showMaximized()
                    }
                }
            }
        }
    }

    // ========== macOS-style buttons (on the left) ==========
    MacTitleBarButtons {
        id: macButtons
        visible: Theme.titleButtonsOnLeft
        anchors.left: parent.left
        anchors.leftMargin: Theme.spacingMd
        anchors.verticalCenter: parent.verticalCenter
        showMaximize: root.showMaximize

        onCloseClicked: root.closeClicked()
        onMinimizeClicked: root.minimizeClicked()
        onMaximizeClicked: {
            // on macOS the green button goes fullscreen
            let win = Window.window
            if (win) {
                if (win.visibility === Window.FullScreen) {
                    win.showNormal()
                } else {
                    win.showFullScreen()
                }
            }
        }
    }

    // the title text: centred on macOS, left-aligned on Windows
    Text {
        anchors.centerIn: Theme.titleButtonsOnLeft ? parent : undefined
        anchors.left: Theme.titleButtonsOnLeft ? undefined : parent.left
        anchors.leftMargin: Theme.titleButtonsOnLeft ? 0 : Theme.spacingLg
        anchors.verticalCenter: Theme.titleButtonsOnLeft ? undefined : parent.verticalCenter
        text: root.title
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeMd
        font.weight: Font.Medium
        color: Theme.textPrimary
    }

    // ========== Windows/Linux-style buttons (on the right) ==========
    Row {
        id: winButtons
        visible: !Theme.titleButtonsOnLeft
        anchors.right: parent.right
        anchors.rightMargin: Theme.spacingSm
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.spacingXs

        // minimise
        Rectangle {
            visible: root.showMinimize
            width: 32
            height: 32
            radius: Theme.radiusSm
            color: minimizeArea.containsMouse ? Theme.backgroundHover : "transparent"

            Text {
                anchors.centerIn: parent
                text: "−"
                font.pixelSize: Theme.fontSizeLg
                color: Theme.textSecondary
            }

            MouseArea {
                id: minimizeArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: root.minimizeClicked()
            }
        }

        // maximise
        Rectangle {
            visible: root.showMaximize
            width: 32
            height: 32
            radius: Theme.radiusSm
            color: maximizeArea.containsMouse ? Theme.backgroundHover : "transparent"

            Text {
                anchors.centerIn: parent
                text: "□"
                font.pixelSize: Theme.fontSizeMd
                color: Theme.textSecondary
            }

            MouseArea {
                id: maximizeArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: root.maximizeClicked()
            }
        }

        // close
        Rectangle {
            visible: root.showClose
            width: 32
            height: 32
            radius: Theme.radiusSm
            color: closeArea.containsMouse ? (closeArea.pressed ? Theme.error : Theme.errorHover) : "transparent"

            Text {
                anchors.centerIn: parent
                text: "×"
                font.pixelSize: Theme.fontSizeXl
                font.weight: Font.Bold
                color: closeArea.containsMouse ? "white" : Theme.textSecondary
            }

            MouseArea {
                id: closeArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: root.closeClicked()
            }
        }
    }
}
