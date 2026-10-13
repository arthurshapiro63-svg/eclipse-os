pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import qs.common
import qs.components

// Month grid with today highlighted and previous / next month. Click the title to jump back.
ColumnLayout {
    id: root

    property date today: new Date()
    property int year: today.getFullYear()
    property int month: today.getMonth()
    readonly property int firstDow: Qt.locale().firstDayOfWeek % 7      // 0 = Sunday
    spacing: 6

    function shift(d) {
        let m = month + d, y = year;
        if (m < 0) { m = 11; y--; } else if (m > 11) { m = 0; y++; }
        month = m; year = y;
    }
    function reset() { year = today.getFullYear(); month = today.getMonth(); }

    readonly property var cells: {
        const first = new Date(year, month, 1);
        const lead = (first.getDay() - firstDow + 7) % 7;
        const out = [];
        for (let i = 0; i < 42; i++) {
            const d = new Date(year, month, 1 - lead + i);
            out.push({ day: d.getDate(), inMonth: d.getMonth() === month,
                       isToday: d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate() });
        }
        return out;
    }

    RowLayout {
        Layout.fillWidth: true
        Label {
            Layout.fillWidth: true
            text: Qt.locale().standaloneMonthName(root.month, Locale.LongFormat) + " " + root.year
            font.pixelSize: Theme.fontLarge
            font.weight: Font.DemiBold
            TapHandler { onTapped: root.reset() }
        }
        PanelButton { icon: "\u{f0141}"; onClicked: root.shift(-1) }
        PanelButton { icon: "\u{f0142}"; onClicked: root.shift(1) }
    }

    GridLayout {
        Layout.fillWidth: true
        columns: 7
        uniformCellWidths: true
        rowSpacing: 2
        columnSpacing: 2

        Repeater {
            model: 7
            delegate: Label {
                required property int index
                Layout.fillWidth: true
                Layout.preferredHeight: 22
                horizontalAlignment: Text.AlignHCenter
                text: Qt.locale().standaloneDayName((root.firstDow + index) % 7, Locale.ShortFormat).slice(0, 2)
                color: Theme.muted
                font.pixelSize: Theme.fontSmall
            }
        }
        Repeater {
            model: root.cells
            delegate: Rectangle {
                id: cell
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                radius: Theme.radiusSm
                color: modelData.isToday ? Theme.accent : "transparent"
                Label {
                    anchors.centerIn: parent
                    text: cell.modelData.day
                    font.family: Theme.fontMono
                    font.weight: cell.modelData.isToday ? Font.Bold : Font.Normal
                    color: cell.modelData.isToday ? Theme.text : cell.modelData.inMonth ? Theme.text : Theme.withAlpha(Theme.muted, 0.6)
                }
            }
        }
    }
}
