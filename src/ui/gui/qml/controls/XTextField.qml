// A custom text field
import QtQuick
import QtQuick.Controls
import "../theme"

TextField {
    id: root

    // whether this is a password field
    property bool isPassword: false
    // whether the password is shown
    property bool passwordVisible: false

    implicitWidth: 200
    implicitHeight: 36

    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSizeSm
    color: enabled ? Theme.textPrimary : Theme.textPlaceholder
    placeholderTextColor: Theme.textPlaceholder
    selectionColor: Theme.primary
    selectedTextColor: "white"
    selectByMouse: true

    leftPadding: Theme.spacingMd
    rightPadding: isPassword ? 40 : Theme.spacingMd

    echoMode: isPassword && !passwordVisible ? TextInput.Password : TextInput.Normal

    background: Rectangle {
        radius: Theme.radiusMd
        color: Theme.backgroundSecondary
        border.width: 1
        border.color: root.activeFocus ? Theme.primary : "transparent"
    }

    // the show/hide password button
    Item {
        visible: root.isPassword
        anchors.right: parent.right
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        width: 28
        height: 28

        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusSm
            color: eyeMouseArea.containsMouse ? Theme.backgroundHover : "transparent"
        }

        // the eye icon (an SVG path)
        Canvas {
            id: eyeIcon
            anchors.centerIn: parent
            width: 18
            height: 18

            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                ctx.strokeStyle = Theme.textSecondary
                ctx.lineWidth = 1.5
                ctx.lineCap = "round"
                ctx.lineJoin = "round"

                // the outline of the eye
                ctx.beginPath()
                ctx.moveTo(1, 9)
                ctx.bezierCurveTo(1, 9, 4, 3, 9, 3)
                ctx.bezierCurveTo(14, 3, 17, 9, 17, 9)
                ctx.bezierCurveTo(17, 9, 14, 15, 9, 15)
                ctx.bezierCurveTo(4, 15, 1, 9, 1, 9)
                ctx.stroke()

                // the pupil
                ctx.beginPath()
                ctx.arc(9, 9, 3, 0, Math.PI * 2)
                ctx.stroke()

                // the slash, shown when hidden
                if (!root.passwordVisible) {
                    ctx.beginPath()
                    ctx.moveTo(3, 15)
                    ctx.lineTo(15, 3)
                    ctx.stroke()
                }
            }
        }

        MouseArea {
            id: eyeMouseArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                root.passwordVisible = !root.passwordVisible
                eyeIcon.requestPaint()
            }
        }
    }
}
