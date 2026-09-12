// A drawn avatar: a cartoon face that reacts live to state, emotion and volume, with no image assets
// Procedural cartoon avatar: expression from the emotion name, mouth from live audio.
import QtQuick
import QtQuick.Shapes
import "../theme"

Item {
    id: root

    // ---- inputs ----
    property string emotion: "neutral"
    property string mode: "idle"          // idle | listening | speaking
    property real level: 0.0              // 0..1 live audio amplitude

    // ---- appearance (tweak here to change who it looks like) ----
    property color skinTop: "#F6D3B0"
    property color skinBottom: "#EBB98D"
    property color skinLine: "#C98E63"
    property color hairColor: "#A87B4A"
    property color hairShade: "#8E6538"
    property color irisColor: "#8A8266"
    property color lipColor: "#B9655C"
    // Off by default: without a blur effect the filled region has a hard edge
    // that sweeps cheek-to-cheek and reads as a second mouth. Set true only if
    // you reshape it to hug the jaw much more tightly.
    property bool stubble: false
    property bool glasses: false

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

    property real smile: face.smile
    property real brow: face.brow
    property real eyeOpen: face.eye
    // Emotion tint is now an accent (halo, blush, status ring), not the skin.
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
    property real gazeX: 0
    property real gazeY: 0
    Behavior on gazeX { NumberAnimation { duration: 620; easing.type: Easing.InOutQuad } }
    Behavior on gazeY { NumberAnimation { duration: 620; easing.type: Easing.InOutQuad } }

    readonly property real headR: 85 * unit

    // ---- listening halo ---------------------------------------------------
    Rectangle {
        anchors.centerIn: head
        width: head.width * (1.14 + root.level * 0.30)
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 2.5 * root.unit
        border.color: root.tint
        opacity: root.mode === "listening" ? (0.30 + root.level * 0.55) : 0.0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Behavior on width { NumberAnimation { duration: 90 } }
    }

    // ---- contact shadow ---------------------------------------------------
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
    Item {
        id: head
        anchors.horizontalCenter: parent.horizontalCenter
        width: 170 * root.unit
        height: 170 * root.unit

        y: parent.height / 2 - height / 2 + breathe - root.level * 4 * root.unit
        rotation: (root.face.tilt === 1 ? -7 : 0) + (root.mode === "listening" ? 3 : 0)
        Behavior on rotation { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }

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

        readonly property real cx: width / 2
        readonly property real cy: height / 2

        // ---- ears (behind the face) ----
        Repeater {
            model: 2
            Rectangle {
                required property int index
                width: 20 * root.unit
                height: 26 * root.unit
                radius: width / 2
                color: root.skinBottom
                border.width: 1.5 * root.unit
                border.color: root.skinLine
                x: index === 0 ? -9 * root.unit : head.width - 11 * root.unit
                y: head.cy - height / 2 + 4 * root.unit
            }
        }

        // ---- face ----
        Rectangle {
            id: faceDisc
            anchors.fill: parent
            radius: width / 2
            border.width: 2 * root.unit
            border.color: root.skinLine
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.skinTop }
                GradientStop { position: 1.0; color: root.skinBottom }
            }
        }

        // ---- stubble: lower arc of the face, subtle ----
        Shape {
            anchors.fill: parent
            visible: root.stubble
            opacity: 0.13
            preferredRendererType: Shape.CurveRenderer
            antialiasing: true
            ShapePath {
                fillColor: "#4A3B33"
                strokeColor: "transparent"
                startX: head.cx - root.headR * 0.74
                startY: head.cy + root.headR * 0.40
                // across the cheeks, dipping under the mouth
                PathCubic {
                    x: head.cx + root.headR * 0.74
                    y: head.cy + root.headR * 0.40
                    control1X: head.cx - root.headR * 0.26
                    control1Y: head.cy + root.headR * 0.70
                    control2X: head.cx + root.headR * 0.26
                    control2Y: head.cy + root.headR * 0.70
                }
                // back along the jaw
                PathArc {
                    x: head.cx - root.headR * 0.74
                    y: head.cy + root.headR * 0.40
                    radiusX: root.headR
                    radiusY: root.headR
                    useLargeArc: false
                    direction: PathArc.Clockwise
                }
            }
        }

        // ---- hair: cap following the skull, with a side part ----
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            antialiasing: true
            ShapePath {
                fillColor: root.hairColor
                strokeColor: root.hairShade
                strokeWidth: 1.5 * root.unit
                // start at the left temple
                startX: head.cx - root.headR * 0.99
                startY: head.cy - root.headR * 0.12
                // over the top of the skull
                PathArc {
                    x: head.cx + root.headR * 0.99
                    y: head.cy - root.headR * 0.12
                    radiusX: root.headR
                    radiusY: root.headR
                    useLargeArc: false
                    direction: PathArc.Clockwise
                }
                // hairline back across the forehead, swept to one side
                PathCubic {
                    x: head.cx - root.headR * 0.99
                    y: head.cy - root.headR * 0.12
                    control1X: head.cx + root.headR * 0.45
                    control1Y: head.cy - root.headR * 0.86
                    control2X: head.cx - root.headR * 0.62
                    control2Y: head.cy - root.headR * 0.30
                }
            }
        }

        // ---- brows ----
        Repeater {
            model: 2
            Rectangle {
                required property int index
                readonly property bool isLeft: index === 0
                width: 30 * root.unit
                height: 6 * root.unit
                radius: height / 2
                color: root.hairShade
                x: head.cx + (isLeft ? -46 : 16) * root.unit + root.gazeX * 0.35
                y: head.cy - 30 * root.unit - root.brow * 8 * root.unit + root.gazeY * 0.3
                rotation: (isLeft ? 1 : -1) * root.brow * -15
                Behavior on y { NumberAnimation { duration: 220 } }
                Behavior on rotation { NumberAnimation { duration: 220 } }
            }
        }

        // ---- eyes ----
        Repeater {
            model: 2
            Item {
                id: eye
                required property int index
                readonly property bool isLeft: index === 0
                readonly property bool shut: (root.face.wink === 1 && !isLeft)
                readonly property real openAmt:
                    root.eyeOpen * root.blink * (shut ? 0.03 : 1.0)

                width: 30 * root.unit
                height: 24 * root.unit
                x: head.cx + (isLeft ? -45 : 15) * root.unit
                y: head.cy - 16 * root.unit
                clip: true          // the lid: clipping is what makes a blink read

                // sclera. clip: true is load-bearing - the iris is a CHILD so the
                // eye opening cuts it. As a sibling it kept its full height while
                // the sclera shrank, and slid out below the lower lid onto the cheek.
                Rectangle {
                    id: sclera
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: (parent.height - height) / 2
                    width: parent.width
                    height: Math.max(1.5 * root.unit, parent.height * eye.openAmt)
                    radius: height / 2
                    color: "#FDFDFB"
                    border.width: 1.2 * root.unit
                    border.color: root.skinLine
                    clip: true
                    Behavior on height { NumberAnimation { duration: 70 } }

                    // iris + pupil track the gaze. A large iris relative to the
                    // sclera is what stops the face reading as a wide-eyed stare.
                    Rectangle {
                        id: iris
                        width: 17.5 * root.unit
                        height: width
                        radius: width / 2
                        color: root.irisColor
                        visible: eye.openAmt > 0.06
                        x: (sclera.width - width) / 2 + root.gazeX * 0.8
                        y: (sclera.height - height) / 2 + root.gazeY * 0.6

                        Rectangle {
                            anchors.centerIn: parent
                            width: 7.5 * root.unit
                            height: width
                            radius: width / 2
                            color: "#2B2320"
                        }
                        Rectangle {
                            width: 5 * root.unit
                            height: width
                            radius: width / 2
                            color: "#FFFFFF"
                            opacity: 0.95
                            x: parent.width * 0.56
                            y: parent.height * 0.14
                        }
                    }
                }

                // relaxed upper lid: covers the top of the iris so the eye looks
                // lidded rather than held wide open. Grows as the eye closes.
                Rectangle {
                    id: lid
                    x: -root.unit
                    y: -root.unit
                    width: parent.width + 2 * root.unit
                    height: sclera.y + sclera.height * 0.26 + root.unit
                    color: root.skinTop
                }

                // lash line sits on the lid edge
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: lid.y + lid.height - 1.2 * root.unit
                    width: parent.width * 0.94
                    height: 2.2 * root.unit
                    radius: height / 2
                    color: root.hairShade
                    opacity: eye.openAmt > 0.1 ? 0.8 : 0.0
                }
            }
        }

        // ---- glasses (optional) ----
        Repeater {
            model: root.glasses ? 2 : 0
            Rectangle {
                required property int index
                width: 38 * root.unit
                height: 30 * root.unit
                radius: 8 * root.unit
                color: "transparent"
                border.width: 2.5 * root.unit
                border.color: "#4A4038"
                x: head.cx + (index === 0 ? -49 : 11) * root.unit
                y: head.cy - 19 * root.unit
            }
        }

        // ---- nose ----
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            antialiasing: true
            ShapePath {
                fillColor: "transparent"
                strokeColor: root.skinLine
                strokeWidth: 2.6 * root.unit
                capStyle: ShapePath.RoundCap
                startX: head.cx + 1 * root.unit + root.gazeX * 0.4
                startY: head.cy + 2 * root.unit
                PathCubic {
                    x: head.cx - 7 * root.unit + root.gazeX * 0.4
                    y: head.cy + 17 * root.unit
                    control1X: head.cx + 4 * root.unit + root.gazeX * 0.4
                    control1Y: head.cy + 12 * root.unit
                    control2X: head.cx + 2 * root.unit + root.gazeX * 0.4
                    control2Y: head.cy + 17 * root.unit
                }
            }
        }

        // ---- blush ----
        Repeater {
            model: 2
            Rectangle {
                required property int index
                width: 22 * root.unit
                height: 11 * root.unit
                radius: height / 2
                color: "#F2827F"
                opacity: root.face.blush === 1 ? 0.45 : 0.0
                x: head.cx + (index === 0 ? -64 : 42) * root.unit
                y: head.cy + 16 * root.unit
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
                x: head.cx + (index === 0 ? -38 : 30) * root.unit
                y: head.cy + 6 * root.unit + drop
                property real drop: 0
                SequentialAnimation on drop {
                    loops: Animation.Infinite
                    running: root.face.tears === 1
                    NumberAnimation { from: 0; to: 30 * root.unit; duration: 1100 }
                    PauseAnimation { duration: 260 }
                }
            }
        }

        // ---- mouth ----
        Shape {
            id: mouth
            width: 90 * root.unit
            height: 60 * root.unit
            anchors.horizontalCenter: parent.horizontalCenter
            y: head.cy + 26 * root.unit
            preferredRendererType: Shape.CurveRenderer
            antialiasing: true

            readonly property real cx: width / 2
            readonly property real cy: height / 4
            readonly property real halfW: 26 * root.unit
            readonly property real curve: root.smile * 22 * root.unit
            readonly property real open: root.mouthOpen * 24 * root.unit
            // approx. depth of the lower lip at the cubic midpoint;
            // the tongue is clamped to this so it cannot poke through
            readonly property real lipDepth: 0.75 * (curve + open)

            ShapePath {
                strokeColor: root.lipColor
                strokeWidth: 4 * root.unit
                fillColor: root.mouthOpen > 0.05 ? "#6E2B2B" : "transparent"
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
                    control1Y: mouth.cy - mouth.open * 0.7
                    control2X: mouth.cx - mouth.halfW * 0.45
                    control2Y: mouth.cy - mouth.open * 0.7
                }
            }

            Rectangle {
                width: 22 * root.unit
                height: 9 * root.unit
                radius: height / 2
                color: "#D9727F"
                opacity: (root.mouthOpen > 0.5
                         && mouth.lipDepth > height + 4 * root.unit) ? 0.9 : 0.0
                x: mouth.cx - width / 2
                y: mouth.cy + Math.max(0, Math.min(mouth.open * 0.5,
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
        NumberAnimation { target: root; property: "blink"; to: 0.04; duration: 70 }
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

    onModeChanged: if (mode === "speaking") { gazeX = 0; gazeY = 0 }
}
