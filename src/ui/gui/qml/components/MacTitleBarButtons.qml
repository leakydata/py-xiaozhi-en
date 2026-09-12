// The macOS-style traffic light buttons
import QtQuick
import QtQuick.Layouts
import "../theme"

Row {
    id: root
    spacing: 8

    signal closeClicked()
    signal minimizeClicked()
    signal maximizeClicked()

    property bool showMaximize: true
    property bool hovered: closeArea.containsMouse || minimizeArea.containsMouse || maximizeArea.containsMouse

    // close (red)
    Rectangle {
        width: 12
        height: 12
        radius: 6
        color: "#FF5F57"
        border.width: 0.5
        border.color: "#E0443E"

        // the cross icon
        Item {
            anchors.centerIn: parent
            width: 6
            height: 6
            visible: root.hovered

            Rectangle {
                width: 8
                height: 1.2
                radius: 0.6
                color: "#4D0000"
                anchors.centerIn: parent
                rotation: 45
            }
            Rectangle {
                width: 8
                height: 1.2
                radius: 0.6
                color: "#4D0000"
                anchors.centerIn: parent
                rotation: -45
            }
        }

        MouseArea {
            id: closeArea
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.closeClicked()
        }
    }

    // minimise (yellow)
    Rectangle {
        width: 12
        height: 12
        radius: 6
        color: "#FEBC2E"
        border.width: 0.5
        border.color: "#DEA123"

        // the dash icon
        Rectangle {
            width: 8
            height: 1.5
            radius: 0.75
            color: "#995700"
            anchors.centerIn: parent
            visible: root.hovered
        }

        MouseArea {
            id: minimizeArea
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.minimizeClicked()
        }
    }

    // maximise (green) - always shown
    Rectangle {
        width: 12
        height: 12
        radius: 6
        color: root.showMaximize ? "#28C840" : "#28C840"
        border.width: 0.5
        border.color: "#14AE28"
        opacity: root.showMaximize ? 1.0 : 0.5

        // the fullscreen icon (two opposing triangles)
        Item {
            anchors.centerIn: parent
            width: 8
            height: 8
            visible: root.hovered && root.showMaximize

            // top-left triangle
            Canvas {
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.fillStyle = "#006500"
                    // top-left triangle
                    ctx.beginPath()
                    ctx.moveTo(1, 1)
                    ctx.lineTo(1, 4)
                    ctx.lineTo(4, 1)
                    ctx.closePath()
                    ctx.fill()
                    // bottom-right triangle
                    ctx.beginPath()
                    ctx.moveTo(7, 7)
                    ctx.lineTo(7, 4)
                    ctx.lineTo(4, 7)
                    ctx.closePath()
                    ctx.fill()
                }
            }
        }

        MouseArea {
            id: maximizeArea
            anchors.fill: parent
            hoverEnabled: true
            enabled: root.showMaximize
            onClicked: if (root.showMaximize) root.maximizeClicked()
        }
    }
}
