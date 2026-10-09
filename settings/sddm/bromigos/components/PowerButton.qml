// A power action in brackets: [ REBOOT ]. warn = armed (amber), waiting for the second press.
import QtQuick

FocusScope {
    id: b
    property string label: ""
    property string about: ""
    property bool warn: false
    property real unit: 1
    property string family: "monospace"
    property var pal
    signal activated()
    signal hovered(bool on)
    width: txt.implicitWidth + 36 * unit
    height: 40 * unit
    activeFocusOnTab: enabled
    opacity: enabled ? 1 : 0.35

    readonly property color tone: warn ? pal.amber : (activeFocus || mouse.containsMouse ? pal.white : pal.soft)

    Rectangle {
        anchors.fill: parent
        color: b.warn ? "#33d4af37" : b.pal.panel
        border.width: 1
        border.color: b.warn ? b.pal.amber : (b.activeFocus || mouse.containsMouse ? b.pal.phosphor : b.pal.guard)
    }
    Text {
        id: txt
        anchors.centerIn: parent
        text: b.label
        color: b.tone
        font.family: b.family
        font.pixelSize: 14 * b.unit
        font.letterSpacing: 3 * b.unit
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        enabled: b.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: b.hovered(true)
        onExited: b.hovered(false)
        onClicked: b.activated()
    }
    Keys.onReturnPressed: b.activated()
    Keys.onEnterPressed: b.activated()
    Keys.onSpacePressed: b.activated()
    onActiveFocusChanged: b.hovered(activeFocus)
}
