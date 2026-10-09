// A terminal-style input line: 1 px phosphor outline on the panel colour, a dim
// "> PROMPT" placeholder, soft text. secret = passphrase (dots). failed = red outline.
import QtQuick

FocusScope {
    id: f
    property alias text: input.text
    property string placeholder: ""
    property string cover: ""          // shown instead of the text (a remembered account, name hidden)
    property string about: ""
    property bool secret: false
    property bool failed: false
    property real unit: 1
    property string family: "monospace"
    property var pal
    signal accepted()
    signal hovered(bool on)
    signal uncover()

    Rectangle {
        anchors.fill: parent
        color: f.pal.panel
        border.width: 1
        border.color: f.failed ? f.pal.danger : (input.activeFocus ? f.pal.phosphor : f.pal.dim)
        Behavior on border.color { ColorAnimation { duration: 220 } }
    }

    Text {                              // the prompt, like a terminal line
        id: prompt
        anchors.verticalCenter: parent.verticalCenter
        x: 18 * f.unit
        text: ">"
        color: input.activeFocus ? f.pal.phosphor : f.pal.dim
        font.family: f.family
        font.pixelSize: 17 * f.unit
    }

    Text {
        anchors.verticalCenter: parent.verticalCenter
        x: 46 * f.unit
        visible: f.cover !== "" || input.text.length === 0
        text: f.cover !== "" ? f.cover : f.placeholder
        color: f.cover !== "" ? f.pal.soft : f.pal.dim
        font.family: f.family
        font.pixelSize: 17 * f.unit
        font.letterSpacing: 3 * f.unit
    }

    TextInput {
        id: input
        focus: true
        anchors.fill: parent
        anchors.leftMargin: 46 * f.unit
        anchors.rightMargin: 18 * f.unit
        verticalAlignment: TextInput.AlignVCenter
        color: f.pal.soft
        selectionColor: f.pal.dim
        selectedTextColor: f.pal.white
        font.family: f.family
        font.pixelSize: (f.secret ? 22 : 18) * f.unit
        font.letterSpacing: (f.secret ? 6 : 2) * f.unit
        echoMode: f.secret ? TextInput.Password : TextInput.Normal
        passwordCharacter: "•"
        passwordMaskDelay: 0
        clip: true
        readOnly: f.cover !== ""
        opacity: f.cover !== "" ? 0 : 1
        cursorDelegate: Rectangle {
            width: (input.text.length === 0 ? 3 : 10) * f.unit
            color: f.pal.phosphor
            visible: input.activeFocus
            SequentialAnimation on opacity {
                running: input.activeFocus
                loops: Animation.Infinite
                NumberAnimation { to: 0.15; duration: 520 }
                NumberAnimation { to: 1.0; duration: 520 }
            }
        }
        Keys.onReturnPressed: f.accepted()
        Keys.onEnterPressed: f.accepted()
        Keys.onEscapePressed: if (f.cover === "") input.text = ""
        Keys.onSpacePressed: function(event) {
            if (f.cover !== "") f.uncover()
            else event.accepted = false
        }
        onActiveFocusChanged: f.hovered(activeFocus)
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.IBeamCursor
        onEntered: f.hovered(true)
        onExited: f.hovered(false)
        onPressed: function(mouse) {
            if (f.cover !== "") f.uncover()
            input.forceActiveFocus()
            mouse.accepted = false
        }
    }
}
