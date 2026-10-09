// The session list, opening upward from its button. Up/Down move, Enter chooses,
// Esc closes; a click chooses. Each row says what it is on hover.
import QtQuick

FocusScope {
    id: m
    property var names: []
    property int current: -1
    property real unit: 1
    property string family: "monospace"
    property var pal
    property bool shown: false
    signal chosen(int index)
    signal closed()
    width: 460 * unit
    height: shown ? list.contentHeight + 20 * unit : 0
    visible: shown
    opacity: shown ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 140 } }

    function open() {
        list.currentIndex = Math.max(0, current)
        shown = true
        list.forceActiveFocus()
    }
    function close() {
        shown = false
        closed()
    }

    Rectangle {
        anchors.fill: parent
        color: m.pal.panel
        border.width: 1
        border.color: m.pal.phosphor
    }
    ListView {
        id: list
        anchors.fill: parent
        anchors.margins: 10 * m.unit
        interactive: false
        model: m.names
        focus: true
        delegate: Rectangle {
            id: row
            required property int index
            required property var modelData
            width: list.width
            height: 40 * m.unit
            color: ListView.isCurrentItem ? m.pal.guard : "transparent"
            Text {
                anchors.verticalCenter: parent.verticalCenter
                x: 14 * m.unit
                text: (row.index === m.current ? "● " : "  ") + String(row.modelData).toUpperCase()
                color: row.ListView.isCurrentItem ? m.pal.white : m.pal.soft
                font.family: m.family
                font.pixelSize: 15 * m.unit
                font.letterSpacing: 2 * m.unit
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onEntered: list.currentIndex = row.index
                onClicked: { m.chosen(row.index); m.close() }
            }
        }
        Keys.onReturnPressed: { m.chosen(currentIndex); m.close() }
        Keys.onEnterPressed: { m.chosen(currentIndex); m.close() }
        Keys.onEscapePressed: m.close()
        Keys.onTabPressed: m.close()
    }
}
