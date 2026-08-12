// 抽象圆盘头像（原版）
// Abstract disc avatar - the original procedural face.
import QtQuick
import QtQuick.Shapes
import "../theme"

Item {
    id: root

    // ---- inputs ----
    property string emotion: "neutral"
    property string mode: "idle"          // idle | listening | speaking
    property real level: 0.0              // 0..1 live audio amplitude

    implicitWidth: 220
    implicitHeight: 220

    readonly property real unit: Math.min(width, height) / 220

    // ---- expression table -------------------------------------------------
    // smile: -1 frown .. 1 grin | brow: -1 angry .. 1 raised
    // eye: lid opening | wink: right eye closed | open: resting mouth aperture
    readonly property var table: ({
        "neutral":     { smile: 0.22, brow: 0.00, eye: 0.92, tint: "#4A90E2" },
        "happy":       { smile: 0.85, brow: 0.15, eye: 0.90, tint: "#F5A623" },
        "laughing":    { smile: 1.00, brow: 0.25, eye: 0.25, tint: "#F5A623", open: 0.50 },
        "funny":       { smile: 0.80, brow: 0.35, eye: 0.80, tint: "#F7B733" },
        "silly":       { smile: 0.70, brow: -0.20, eye: 1.10, tint: "#F7B733", open: 0.20 },
        "loving":      { smile: 0.70, brow: 0.20, eye: 0.85, tint: "#FF6B9D", blush: 1 },
        "kissy":       { smile: 0.35, brow: 0.10, eye: 0.45, tint: "#FF6B9D", blush: 1, open: 0.18 },
        "confident":   { smile: 0.50, brow: -0.30, eye: 0.90, tint: "#3DBD7D" },
        "cool":        { smile: 0.30, brow: -0.20, eye: 0.70, tint: "#3DBD7D" },
        "relaxed":     { smile: 0.45, brow: 0.10, eye: 0.45, tint: "#3DBD7D" },
        "delicious":   { smile: 0.80, brow: 0.10, eye: 0.35, tint: "#F5A623", open: 0.30 },
        "winking":     { smile: 0.60, brow: 0.10, eye: 0.95, tint: "#F5A623", wink: 1 },
        "surprised":   { smile: 0.00, brow: 0.80, eye: 1.30, tint: "#4A90E2", open: 0.45 },
        "shocked":     { smile: -0.20, brow: 1.00, eye: 1.45, tint: "#7B61FF", open: 0.70 },
        "thinking":    { smile: -0.10, brow: 0.45, eye: 0.90, tint: "#7B61FF", tilt: 1 },
        "confused":    { smile: -0.25, brow: 0.55, eye: 1.00, tint: "#7B61FF", tilt: 1 },
        "embarrassed": { smile: 0.20, brow: 0.50, eye: 0.70, tint: "#FF6B9D", blush: 1 },
        "sad":         { smile: -0.75, brow: 0.70, eye: 0.85, tint: "#5B8DEF" },
        "crying":      { smile: -0.90, brow: 0.80, eye: 0.55, tint: "#5B8DEF", tears: 1 },
        "angry":       { smile: -0.70, brow: -1.00, eye: 1.00, tint: "#F5515F" },
        "sleepy":      { smile: 0.10, brow: 0.20, eye: 0.12, tint: "#8E9AAF" }
    })

    readonly property var face: table[emotion] !== undefined ? table[emotion] : table["neutral"]

    // Animated so expression changes ease instead of snapping.
    property real smile: face.smile
    property real brow: face.brow
    property real eyeOpen: face.eye
    property color tint: face.tint
    Behavior on smile { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    Behavior on brow { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    Behavior on eyeOpen { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
    Behavior on tint { ColorAnimation { duration: 400 } }

    readonly property real restOpen: face.open !== undefined ? face.open : 0.0
    readonly property real mouthOpen: mode === "speaking"
        ? Math.max(restOpen * 0.4, Math.min(1.0, level * 1.15))
        : restOpen

    property real blink: 1.0
    // Idle gaze wander: small offsets retargeted every few seconds so the eyes
    // never sit perfectly still, which is what reads as "dead" in a static face.
    property real gazeX: 0
    property real gazeY: 0
    Behavior on gazeX { NumberAnimation { duration: 620; easing.type: Easing.InOutQuad } }
    Behavior on gazeY { NumberAnimation { duration: 620; easing.type: Easing.InOutQuad } }

    // ---- listening halo ---------------------------------------------------
    Rectangle {
        anchors.centerIn: head
        width: head.width * (1.12 + root.level * 0.30)
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 2 * root.unit
        border.color: root.tint
        opacity: root.mode === "listening" ? (0.25 + root.level * 0.55) : 0.0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Behavior on width { NumberAnimation { duration: 90 } }
    }

    // ---- contact shadow ---------------------------------------------------
    // Stacked low-opacity ellipses approximate a blur; Qt's blur effect lives in
    // Qt5Compat.GraphicalEffects, which is a heavier dependency than this is worth.
    Repeater {
        model: 3
        Rectangle {
            required property int index
            width: head.width * (0.46 + index * 0.06)
            height: 5 * root.unit * (1 + index * 0.3)
            radius: height / 2
            color: "#000000"
            opacity: 0.045
            x: head.x + (head.width - width) / 2
            y: head.y + head.height - 6 * root.unit
        }
    }

    // ---- head -------------------------------------------------------------
    Rectangle {
        id: head
        anchors.horizontalCenter: parent.horizontalCenter
        width: 170 * root.unit
        height: 170 * root.unit
        radius: width / 2
        border.width: 3 * root.unit
        border.color: root.tint

        // vertical gradient gives the flat disc some volume
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.lighter(root.tint, 1.92) }
            GradientStop { position: 1.0; color: Qt.lighter(root.tint, 1.42) }
        }

        // breathing + speech bob
        y: parent.height / 2 - height / 2 + breathe - root.level * 4 * root.unit
        rotation: (root.face.tilt === 1 ? -7 : 0) + (root.mode === "listening" ? 3 : 0)
        Behavior on rotation { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }

        // squash & stretch: volume is conserved, so it reads as breath not scaling
        transform: Scale {
            origin.x: head.width / 2
            origin.y: head.height
            xScale: 1 + head.breathe * 0.004
            yScale: 1 - head.breathe * 0.004
        }

        property real breathe: 0
        SequentialAnimation on breathe {
            loops: Animation.Infinite
            running: true
            NumberAnimation { to: 3.5; duration: 1900; easing.type: Easing.InOutSine }
            NumberAnimation { to: -3.5; duration: 1900; easing.type: Easing.InOutSine }
        }

        // specular highlight, upper left
        Rectangle {
            width: head.width * 0.26
            height: head.height * 0.15
            radius: width / 2
            color: "#FFFFFF"
            opacity: 0.20
            rotation: -24
            x: head.width * 0.17
            y: head.height * 0.12
        }

        // ---- brows ----
        Repeater {
            model: 2
            Rectangle {
                required property int index
                readonly property bool isLeft: index === 0
                width: 34 * root.unit
                height: 5 * root.unit
                radius: height / 2
                color: root.tint
                x: head.width / 2 + (isLeft ? -56 : 22) * root.unit + root.gazeX * 0.4
                y: head.height * 0.30 - root.brow * 9 * root.unit + root.gazeY * 0.3
                rotation: (isLeft ? 1 : -1) * root.brow * -16
                Behavior on y { NumberAnimation { duration: 220 } }
                Behavior on rotation { NumberAnimation { duration: 220 } }
            }
        }

        // ---- eyes ----
        Repeater {
            model: 2
            Item {
                required property int index
                readonly property bool isLeft: index === 0
                readonly property bool shut: (root.face.wink === 1 && !isLeft)
                readonly property real openAmt:
                    root.eyeOpen * root.blink * (shut ? 0.05 : 1.0)

                width: 22 * root.unit
                height: 22 * root.unit
                x: head.width / 2 + (isLeft ? -51 : 29) * root.unit + root.gazeX
                y: head.height * 0.44 - height / 2 + root.gazeY

                // eye body
                Rectangle {
                    id: ball
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.verticalCenter: parent.verticalCenter
                    width: 22 * root.unit
                    height: Math.max(2.5 * root.unit, 22 * root.unit * parent.openAmt)
                    radius: width / 2
                    color: Qt.darker(root.tint, 1.25)
                    Behavior on height { NumberAnimation { duration: 70 } }
                }

                // catchlight — the single biggest "alive" cue on a flat eye
                Rectangle {
                    width: 7 * root.unit
                    height: width
                    radius: width / 2
                    color: "#FFFFFF"
                    opacity: parent.openAmt > 0.35 ? 0.92 : 0.0
                    x: ball.x + 11 * root.unit
                    y: ball.y + 3 * root.unit
                    Behavior on opacity { NumberAnimation { duration: 80 } }
                }
            }
        }

        // ---- blush ----
        Repeater {
            model: 2
            Rectangle {
                required property int index
                width: 22 * root.unit
                height: 12 * root.unit
                radius: height / 2
                color: "#FF8FB1"
                opacity: root.face.blush === 1 ? 0.55 : 0.0
                x: head.width / 2 + (index === 0 ? -68 : 46) * root.unit
                y: head.height * 0.55
                Behavior on opacity { NumberAnimation { duration: 300 } }
            }
        }

        // ---- tears ----
        Repeater {
            model: 2
            Rectangle {
                required property int index
                width: 7 * root.unit
                height: 11 * root.unit
                radius: width / 2
                color: "#5B8DEF"
                opacity: root.face.tears === 1 ? 0.9 : 0.0
                x: head.width / 2 + (index === 0 ? -46 : 34) * root.unit
                y: head.height * 0.50 + drop
                property real drop: 0
                SequentialAnimation on drop {
                    loops: Animation.Infinite
                    running: root.face.tears === 1
                    NumberAnimation { from: 0; to: 34 * root.unit; duration: 1100 }
                    PauseAnimation { duration: 260 }
                }
            }
        }

        // ---- mouth ----
        Shape {
            id: mouth
            width: 90 * root.unit
            height: 66 * root.unit
            anchors.horizontalCenter: parent.horizontalCenter
            y: head.height * 0.60
            preferredRendererType: Shape.CurveRenderer
            antialiasing: true

            readonly property real cx: width / 2
            readonly property real cy: height / 3
            readonly property real halfW: 30 * root.unit
            readonly property real curve: root.smile * 26 * root.unit
            readonly property real open: root.mouthOpen * 26 * root.unit
            // approx. depth of the lower lip at the cubic midpoint;
            // the tongue is clamped to this so it cannot poke through
            readonly property real lipDepth: 0.75 * (curve + open)

            ShapePath {
                strokeColor: root.tint
                strokeWidth: 4.5 * root.unit
                fillColor: root.mouthOpen > 0.05 ? Qt.darker(root.tint, 1.5) : "transparent"
                capStyle: ShapePath.RoundCap
                startX: mouth.cx - mouth.halfW
                startY: mouth.cy

                PathCubic {
                    x: mouth.cx + mouth.halfW
                    y: mouth.cy
                    control1X: mouth.cx - mouth.halfW * 0.45
                    control1Y: mouth.cy + mouth.curve + mouth.open
                    control2X: mouth.cx + mouth.halfW * 0.45
                    control2Y: mouth.cy + mouth.curve + mouth.open
                }
                PathCubic {
                    x: mouth.cx - mouth.halfW
                    y: mouth.cy
                    control1X: mouth.cx + mouth.halfW * 0.45
                    control1Y: mouth.cy - mouth.open * 0.75
                    control2X: mouth.cx - mouth.halfW * 0.45
                    control2Y: mouth.cy - mouth.open * 0.75
                }
            }

            // tongue: only visible once the mouth is properly open
            Rectangle {
                width: 26 * root.unit
                height: 10 * root.unit
                radius: height / 2
                color: "#FF7C93"
                opacity: (root.mouthOpen > 0.45
                         && mouth.lipDepth > height + 4 * root.unit) ? 0.85 : 0.0
                x: mouth.cx - width / 2
                y: mouth.cy + Math.max(0, Math.min(mouth.open * 0.55,
                                   mouth.lipDepth - height - 2 * root.unit))
                Behavior on opacity { NumberAnimation { duration: 120 } }
            }
        }
    }

    // ---- blinking ---------------------------------------------------------
    Timer {
        interval: 2600 + Math.random() * 3600
        running: root.face.eye > 0.3
        repeat: true
        onTriggered: {
            blinkAnim.restart()
            interval = 2600 + Math.random() * 3600
        }
    }

    SequentialAnimation {
        id: blinkAnim
        NumberAnimation { target: root; property: "blink"; to: 0.05; duration: 70 }
        NumberAnimation { target: root; property: "blink"; to: 1.0; duration: 110 }
    }

    // ---- idle gaze wander -------------------------------------------------
    Timer {
        interval: 1800 + Math.random() * 2600
        running: root.mode !== "speaking"
        repeat: true
        onTriggered: {
            root.gazeX = (Math.random() - 0.5) * 7 * root.unit
            root.gazeY = (Math.random() - 0.5) * 4 * root.unit
            interval = 1800 + Math.random() * 2600
        }
    }

    // Look straight ahead while talking to the user.
    onModeChanged: if (mode === "speaking") { gazeX = 0; gazeY = 0 }
}
