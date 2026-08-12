// 程序化头像：随状态/情绪/音量实时变化，无需图片资源
// Procedural avatar: expression from the emotion name, mouth from live audio.
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
    // eye: lid opening | wink: right eye closed | extra: blush / tears
    readonly property var table: ({
        "neutral":     { smile: 0.05, brow: 0.00, eye: 1.00, tint: "#4A90E2" },
        "happy":       { smile: 0.85, brow: 0.15, eye: 0.90, tint: "#F5A623" },
        "laughing":    { smile: 1.00, brow: 0.25, eye: 0.25, tint: "#F5A623" , open: 0.5 },
        "funny":       { smile: 0.80, brow: 0.35, eye: 0.80, tint: "#F7B733" },
        "silly":       { smile: 0.70, brow: -0.20, eye: 1.10, tint: "#F7B733" , open: 0.2 },
        "loving":      { smile: 0.70, brow: 0.20, eye: 0.85, tint: "#FF6B9D", blush: 1 },
        "kissy":       { smile: 0.35, brow: 0.10, eye: 0.45, tint: "#FF6B9D", blush: 1 , open: 0.18 },
        "confident":   { smile: 0.50, brow: -0.30, eye: 0.90, tint: "#3DBD7D" },
        "cool":        { smile: 0.30, brow: -0.20, eye: 0.70, tint: "#3DBD7D" },
        "relaxed":     { smile: 0.45, brow: 0.10, eye: 0.45, tint: "#3DBD7D" },
        "delicious":   { smile: 0.80, brow: 0.10, eye: 0.35, tint: "#F5A623" , open: 0.3 },
        "winking":     { smile: 0.60, brow: 0.10, eye: 0.95, tint: "#F5A623", wink: 1 },
        "surprised":   { smile: 0.00, brow: 0.80, eye: 1.30, tint: "#4A90E2" , open: 0.45 },
        "shocked":     { smile: -0.20, brow: 1.00, eye: 1.45, tint: "#7B61FF" , open: 0.7 },
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

    // Mouth opening: speech drives it, otherwise closed.
    readonly property real restOpen: face.open !== undefined ? face.open : 0.0
    readonly property real mouthOpen: mode === "speaking"
        ? Math.max(restOpen * 0.4, Math.min(1.0, level * 1.15))
        : restOpen
    // Blink multiplier, driven by the timer below.
    property real blink: 1.0

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

    // ---- head -------------------------------------------------------------
    Rectangle {
        id: head
        anchors.centerIn: parent
        width: 170 * root.unit
        height: 170 * root.unit
        radius: width / 2
        color: Qt.lighter(root.tint, 1.72)
        border.width: 3 * root.unit
        border.color: root.tint
        // breathing + a small lean when thinking
        y: parent.height / 2 - height / 2 + breathe
        rotation: (root.face.tilt === 1 ? -7 : 0) + (root.mode === "listening" ? 3 : 0)
        Behavior on rotation { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }

        property real breathe: 0
        SequentialAnimation on breathe {
            loops: Animation.Infinite
            running: true
            NumberAnimation { to: 3.5; duration: 1900; easing.type: Easing.InOutSine }
            NumberAnimation { to: -3.5; duration: 1900; easing.type: Easing.InOutSine }
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
                x: head.width / 2 + (isLeft ? -56 : 22) * root.unit
                y: head.height * 0.30 - root.brow * 9 * root.unit
                rotation: (isLeft ? 1 : -1) * root.brow * -16
                Behavior on y { NumberAnimation { duration: 220 } }
                Behavior on rotation { NumberAnimation { duration: 220 } }
            }
        }

        // ---- eyes ----
        Repeater {
            model: 2
            Rectangle {
                required property int index
                readonly property bool isLeft: index === 0
                readonly property bool shut: (root.face.wink === 1 && !isLeft)
                width: 20 * root.unit
                height: Math.max(2 * root.unit,
                                 20 * root.unit * root.eyeOpen * root.blink * (shut ? 0.05 : 1.0))
                radius: width / 2
                color: root.tint
                x: head.width / 2 + (isLeft ? -50 : 30) * root.unit
                y: head.height * 0.44 - height / 2
                Behavior on height { NumberAnimation { duration: 70 } }
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
            // grin widens the mouth, speech opens it
            readonly property real curve: root.smile * 26 * root.unit
            readonly property real open: root.mouthOpen * 26 * root.unit

            ShapePath {
                strokeColor: root.tint
                strokeWidth: 4.5 * root.unit
                fillColor: root.mouthOpen > 0.05 ? Qt.darker(root.tint, 1.35) : "transparent"
                capStyle: ShapePath.RoundCap
                startX: mouth.cx - mouth.halfW
                startY: mouth.cy

                // lower lip: smile curve plus the speech opening
                PathCubic {
                    x: mouth.cx + mouth.halfW
                    y: mouth.cy
                    control1X: mouth.cx - mouth.halfW * 0.45
                    control1Y: mouth.cy + mouth.curve + mouth.open
                    control2X: mouth.cx + mouth.halfW * 0.45
                    control2Y: mouth.cy + mouth.curve + mouth.open
                }
                // upper lip: only bows out once the mouth is open
                PathCubic {
                    x: mouth.cx - mouth.halfW
                    y: mouth.cy
                    control1X: mouth.cx + mouth.halfW * 0.45
                    control1Y: mouth.cy - mouth.open * 0.75
                    control2X: mouth.cx - mouth.halfW * 0.45
                    control2Y: mouth.cy - mouth.open * 0.75
                }
            }
        }
    }

    // ---- blinking ---------------------------------------------------------
    Timer {
        interval: 2600 + Math.random() * 3600
        running: root.face.eye > 0.3   // asleep/squinting faces don't blink
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
}
