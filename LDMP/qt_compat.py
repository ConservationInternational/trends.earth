"""
Qt5/Qt6 compatibility shim for QGIS 3/4 support.

In Qt6 (QGIS 4), many Qt namespace members were moved into scoped enum classes
(e.g. Qt.DisplayRole → Qt.ItemDataRole.DisplayRole). This module patches the Qt
class and affected widget classes with flat aliases so existing Qt5-style code
continues to work unmodified.

Call apply_qt_compat() once at plugin startup before any other imports.
"""

from qgis.PyQt.QtCore import QEvent, QIODevice, QItemSelectionModel, QJsonDocument, Qt
from qgis.PyQt.QtGui import QFont, QPainter, QPalette
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QToolButton,
)


def patch(cls, mappings):
    for attr, value in mappings.items():
        if not hasattr(cls, attr):
            try:
                setattr(cls, attr, value)
            except (AttributeError, TypeError):
                pass


def apply_qt_compat():
    """Add Qt5-style flat enum aliases to Qt and widget classes for Qt6 compatibility."""
    if hasattr(Qt, "DisplayRole"):
        return

    # Qt namespace
    patch(
        Qt,
        {
            # ItemDataRole
            "DisplayRole": Qt.ItemDataRole.DisplayRole,
            "UserRole": Qt.ItemDataRole.UserRole,
            "EditRole": Qt.ItemDataRole.EditRole,
            "ToolTipRole": Qt.ItemDataRole.ToolTipRole,
            "DecorationRole": Qt.ItemDataRole.DecorationRole,
            "BackgroundRole": Qt.ItemDataRole.BackgroundRole,
            "ForegroundRole": Qt.ItemDataRole.ForegroundRole,
            "CheckStateRole": Qt.ItemDataRole.CheckStateRole,
            "SizeHintRole": Qt.ItemDataRole.SizeHintRole,
            "StatusTipRole": Qt.ItemDataRole.StatusTipRole,
            "FontRole": Qt.ItemDataRole.FontRole,
            "TextAlignmentRole": Qt.ItemDataRole.TextAlignmentRole,
            "WhatsThisRole": Qt.ItemDataRole.WhatsThisRole,
            "InitialSortOrderRole": Qt.ItemDataRole.InitialSortOrderRole,
            # CheckState
            "Checked": Qt.CheckState.Checked,
            "Unchecked": Qt.CheckState.Unchecked,
            "PartiallyChecked": Qt.CheckState.PartiallyChecked,
            # Orientation
            "Horizontal": Qt.Orientation.Horizontal,
            "Vertical": Qt.Orientation.Vertical,
            # AlignmentFlag
            "AlignLeft": Qt.AlignmentFlag.AlignLeft,
            "AlignRight": Qt.AlignmentFlag.AlignRight,
            "AlignCenter": Qt.AlignmentFlag.AlignCenter,
            "AlignTop": Qt.AlignmentFlag.AlignTop,
            "AlignBottom": Qt.AlignmentFlag.AlignBottom,
            "AlignHCenter": Qt.AlignmentFlag.AlignHCenter,
            "AlignVCenter": Qt.AlignmentFlag.AlignVCenter,
            "AlignJustify": Qt.AlignmentFlag.AlignJustify,
            # ItemFlag
            "ItemIsEnabled": Qt.ItemFlag.ItemIsEnabled,
            "ItemIsSelectable": Qt.ItemFlag.ItemIsSelectable,
            "ItemIsEditable": Qt.ItemFlag.ItemIsEditable,
            "ItemIsUserCheckable": Qt.ItemFlag.ItemIsUserCheckable,
            "ItemIsUserTristate": Qt.ItemFlag.ItemIsUserTristate,
            "ItemIsDragEnabled": Qt.ItemFlag.ItemIsDragEnabled,
            "ItemIsDropEnabled": Qt.ItemFlag.ItemIsDropEnabled,
            # PenStyle
            "NoPen": Qt.PenStyle.NoPen,
            "SolidLine": Qt.PenStyle.SolidLine,
            "DashLine": Qt.PenStyle.DashLine,
            "DotLine": Qt.PenStyle.DotLine,
            "DashDotLine": Qt.PenStyle.DashDotLine,
            # GlobalColor
            "white": Qt.GlobalColor.white,
            "black": Qt.GlobalColor.black,
            "red": Qt.GlobalColor.red,
            "blue": Qt.GlobalColor.blue,
            "green": Qt.GlobalColor.green,
            "gray": Qt.GlobalColor.gray,
            "darkRed": Qt.GlobalColor.darkRed,
            "darkGreen": Qt.GlobalColor.darkGreen,
            "darkBlue": Qt.GlobalColor.darkBlue,
            "darkGray": Qt.GlobalColor.darkGray,
            "lightGray": Qt.GlobalColor.lightGray,
            "yellow": Qt.GlobalColor.yellow,
            "cyan": Qt.GlobalColor.cyan,
            "magenta": Qt.GlobalColor.magenta,
            "transparent": Qt.GlobalColor.transparent,
            # CursorShape
            "ArrowCursor": Qt.CursorShape.ArrowCursor,
            "WaitCursor": Qt.CursorShape.WaitCursor,
            "PointingHandCursor": Qt.CursorShape.PointingHandCursor,
            "CrossCursor": Qt.CursorShape.CrossCursor,
            "SizeAllCursor": Qt.CursorShape.SizeAllCursor,
            "IBeamCursor": Qt.CursorShape.IBeamCursor,
            "BusyCursor": Qt.CursorShape.BusyCursor,
            # Key
            "Key_Escape": Qt.Key.Key_Escape,
            "Key_Enter": Qt.Key.Key_Enter,
            "Key_Return": Qt.Key.Key_Return,
            "Key_Delete": Qt.Key.Key_Delete,
            "Key_Backspace": Qt.Key.Key_Backspace,
            "Key_Tab": Qt.Key.Key_Tab,
            "Key_Space": Qt.Key.Key_Space,
            "Key_Up": Qt.Key.Key_Up,
            "Key_Down": Qt.Key.Key_Down,
            "Key_Left": Qt.Key.Key_Left,
            "Key_Right": Qt.Key.Key_Right,
            # MouseButton
            "LeftButton": Qt.MouseButton.LeftButton,
            "RightButton": Qt.MouseButton.RightButton,
            "MiddleButton": Qt.MouseButton.MiddleButton,
            "NoButton": Qt.MouseButton.NoButton,
            # ScrollBarPolicy
            "ScrollBarAlwaysOff": Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
            "ScrollBarAlwaysOn": Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
            "ScrollBarAsNeeded": Qt.ScrollBarPolicy.ScrollBarAsNeeded,
            # WindowType
            "Window": Qt.WindowType.Window,
            "Dialog": Qt.WindowType.Dialog,
            "Popup": Qt.WindowType.Popup,
            "Tool": Qt.WindowType.Tool,
            "ToolTip": Qt.WindowType.ToolTip,
            "WindowCloseButtonHint": Qt.WindowType.WindowCloseButtonHint,
            "WindowMinMaxButtonsHint": Qt.WindowType.WindowMinMaxButtonsHint,
            "WindowStaysOnTopHint": Qt.WindowType.WindowStaysOnTopHint,
            "WindowMinimizeButtonHint": Qt.WindowType.WindowMinimizeButtonHint,
            "WindowMaximizeButtonHint": Qt.WindowType.WindowMaximizeButtonHint,
            "WindowTitleHint": Qt.WindowType.WindowTitleHint,
            "CustomizeWindowHint": Qt.WindowType.CustomizeWindowHint,
            # AspectRatioMode
            "KeepAspectRatio": Qt.AspectRatioMode.KeepAspectRatio,
            "IgnoreAspectRatio": Qt.AspectRatioMode.IgnoreAspectRatio,
            "KeepAspectRatioByExpanding": Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            # MatchFlag
            "MatchExactly": Qt.MatchFlag.MatchExactly,
            "MatchContains": Qt.MatchFlag.MatchContains,
            "MatchStartsWith": Qt.MatchFlag.MatchStartsWith,
            "MatchEndsWith": Qt.MatchFlag.MatchEndsWith,
            "MatchCaseSensitive": Qt.MatchFlag.MatchCaseSensitive,
            "MatchRecursive": Qt.MatchFlag.MatchRecursive,
            # SortOrder
            "AscendingOrder": Qt.SortOrder.AscendingOrder,
            "DescendingOrder": Qt.SortOrder.DescendingOrder,
            # CaseSensitivity
            "CaseSensitive": Qt.CaseSensitivity.CaseSensitive,
            "CaseInsensitive": Qt.CaseSensitivity.CaseInsensitive,
            # DockWidgetArea
            "LeftDockWidgetArea": Qt.DockWidgetArea.LeftDockWidgetArea,
            "RightDockWidgetArea": Qt.DockWidgetArea.RightDockWidgetArea,
            "TopDockWidgetArea": Qt.DockWidgetArea.TopDockWidgetArea,
            "BottomDockWidgetArea": Qt.DockWidgetArea.BottomDockWidgetArea,
            "AllDockWidgetAreas": Qt.DockWidgetArea.AllDockWidgetAreas,
            "NoDockWidgetArea": Qt.DockWidgetArea.NoDockWidgetArea,
            # ConnectionType
            "AutoConnection": Qt.ConnectionType.AutoConnection,
            "QueuedConnection": Qt.ConnectionType.QueuedConnection,
            "DirectConnection": Qt.ConnectionType.DirectConnection,
            # FocusPolicy
            "StrongFocus": Qt.FocusPolicy.StrongFocus,
            "NoFocus": Qt.FocusPolicy.NoFocus,
            "ClickFocus": Qt.FocusPolicy.ClickFocus,
            "TabFocus": Qt.FocusPolicy.TabFocus,
            "WheelFocus": Qt.FocusPolicy.WheelFocus,
            # BrushStyle
            "NoBrush": Qt.BrushStyle.NoBrush,
            "SolidPattern": Qt.BrushStyle.SolidPattern,
            "Dense1Pattern": Qt.BrushStyle.Dense1Pattern,
            "Dense2Pattern": Qt.BrushStyle.Dense2Pattern,
            "Dense3Pattern": Qt.BrushStyle.Dense3Pattern,
            "Dense4Pattern": Qt.BrushStyle.Dense4Pattern,
            "Dense5Pattern": Qt.BrushStyle.Dense5Pattern,
            "Dense6Pattern": Qt.BrushStyle.Dense6Pattern,
            "Dense7Pattern": Qt.BrushStyle.Dense7Pattern,
            "HorPattern": Qt.BrushStyle.HorPattern,
            "VerPattern": Qt.BrushStyle.VerPattern,
            "CrossPattern": Qt.BrushStyle.CrossPattern,
            "BDiagPattern": Qt.BrushStyle.BDiagPattern,
            "FDiagPattern": Qt.BrushStyle.FDiagPattern,
            "DiagCrossPattern": Qt.BrushStyle.DiagCrossPattern,
            # ArrowType
            "NoArrow": Qt.ArrowType.NoArrow,
            "UpArrow": Qt.ArrowType.UpArrow,
            "DownArrow": Qt.ArrowType.DownArrow,
            "LeftArrow": Qt.ArrowType.LeftArrow,
            "RightArrow": Qt.ArrowType.RightArrow,
            # ToolButtonStyle
            "ToolButtonIconOnly": Qt.ToolButtonStyle.ToolButtonIconOnly,
            "ToolButtonTextOnly": Qt.ToolButtonStyle.ToolButtonTextOnly,
            "ToolButtonTextBesideIcon": Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
            "ToolButtonTextUnderIcon": Qt.ToolButtonStyle.ToolButtonTextUnderIcon,
            "ToolButtonFollowStyle": Qt.ToolButtonStyle.ToolButtonFollowStyle,
            # TextElideMode
            "ElideLeft": Qt.TextElideMode.ElideLeft,
            "ElideRight": Qt.TextElideMode.ElideRight,
            "ElideMiddle": Qt.TextElideMode.ElideMiddle,
            "ElideNone": Qt.TextElideMode.ElideNone,
            # ContextMenuPolicy
            "NoContextMenu": Qt.ContextMenuPolicy.NoContextMenu,
            "PreventContextMenu": Qt.ContextMenuPolicy.PreventContextMenu,
            "DefaultContextMenu": Qt.ContextMenuPolicy.DefaultContextMenu,
            "ActionsContextMenu": Qt.ContextMenuPolicy.ActionsContextMenu,
            "CustomContextMenu": Qt.ContextMenuPolicy.CustomContextMenu,
            # TextInteractionFlag
            "TextSelectableByMouse": Qt.TextInteractionFlag.TextSelectableByMouse,
            "TextBrowserInteraction": Qt.TextInteractionFlag.TextBrowserInteraction,
            "LinksAccessibleByMouse": Qt.TextInteractionFlag.LinksAccessibleByMouse,
        },
    )

    # QToolButton
    patch(
        QToolButton,
        {
            "MenuButtonPopup": QToolButton.ToolButtonPopupMode.MenuButtonPopup,
            "InstantPopup": QToolButton.ToolButtonPopupMode.InstantPopup,
            "DelayedPopup": QToolButton.ToolButtonPopupMode.DelayedPopup,
        },
    )

    # QAbstractItemView
    patch(
        QAbstractItemView,
        {
            "SelectRows": QAbstractItemView.SelectionBehavior.SelectRows,
            "SelectColumns": QAbstractItemView.SelectionBehavior.SelectColumns,
            "SelectItems": QAbstractItemView.SelectionBehavior.SelectItems,
            "SingleSelection": QAbstractItemView.SelectionMode.SingleSelection,
            "MultiSelection": QAbstractItemView.SelectionMode.MultiSelection,
            "ExtendedSelection": QAbstractItemView.SelectionMode.ExtendedSelection,
            "ContiguousSelection": QAbstractItemView.SelectionMode.ContiguousSelection,
            "NoSelection": QAbstractItemView.SelectionMode.NoSelection,
            "NoEditTriggers": QAbstractItemView.EditTrigger.NoEditTriggers,
            "AllEditTriggers": QAbstractItemView.EditTrigger.AllEditTriggers,
            "DoubleClicked": QAbstractItemView.EditTrigger.DoubleClicked,
            "SelectedClicked": QAbstractItemView.EditTrigger.SelectedClicked,
            "EditKeyPressed": QAbstractItemView.EditTrigger.EditKeyPressed,
            "ScrollPerPixel": QAbstractItemView.ScrollMode.ScrollPerPixel,
            "ScrollPerItem": QAbstractItemView.ScrollMode.ScrollPerItem,
        },
    )

    # QHeaderView
    patch(
        QHeaderView,
        {
            "Stretch": QHeaderView.ResizeMode.Stretch,
            "ResizeToContents": QHeaderView.ResizeMode.ResizeToContents,
            "Fixed": QHeaderView.ResizeMode.Fixed,
            "Interactive": QHeaderView.ResizeMode.Interactive,
            "Custom": QHeaderView.ResizeMode.Custom,
        },
    )

    # QSizePolicy
    patch(
        QSizePolicy,
        {
            "Fixed": QSizePolicy.Policy.Fixed,
            "Minimum": QSizePolicy.Policy.Minimum,
            "Maximum": QSizePolicy.Policy.Maximum,
            "Preferred": QSizePolicy.Policy.Preferred,
            "Expanding": QSizePolicy.Policy.Expanding,
            "MinimumExpanding": QSizePolicy.Policy.MinimumExpanding,
            "Ignored": QSizePolicy.Policy.Ignored,
        },
    )

    # QFrame
    patch(
        QFrame,
        {
            "NoFrame": QFrame.Shape.NoFrame,
            "Box": QFrame.Shape.Box,
            "Panel": QFrame.Shape.Panel,
            "StyledPanel": QFrame.Shape.StyledPanel,
            "Plain": QFrame.Shadow.Plain,
            "Raised": QFrame.Shadow.Raised,
            "Sunken": QFrame.Shadow.Sunken,
        },
    )

    # QMessageBox
    patch(
        QMessageBox,
        {
            "Ok": QMessageBox.StandardButton.Ok,
            "Cancel": QMessageBox.StandardButton.Cancel,
            "Yes": QMessageBox.StandardButton.Yes,
            "No": QMessageBox.StandardButton.No,
            "Close": QMessageBox.StandardButton.Close,
            "Save": QMessageBox.StandardButton.Save,
            "Discard": QMessageBox.StandardButton.Discard,
            "Apply": QMessageBox.StandardButton.Apply,
            "Reset": QMessageBox.StandardButton.Reset,
            "Information": QMessageBox.Icon.Information,
            "Warning": QMessageBox.Icon.Warning,
            "Critical": QMessageBox.Icon.Critical,
            "Question": QMessageBox.Icon.Question,
        },
    )

    # QDialogButtonBox
    patch(
        QDialogButtonBox,
        {
            "Ok": QDialogButtonBox.StandardButton.Ok,
            "Cancel": QDialogButtonBox.StandardButton.Cancel,
            "Yes": QDialogButtonBox.StandardButton.Yes,
            "No": QDialogButtonBox.StandardButton.No,
            "Close": QDialogButtonBox.StandardButton.Close,
            "Save": QDialogButtonBox.StandardButton.Save,
            "Discard": QDialogButtonBox.StandardButton.Discard,
            "Apply": QDialogButtonBox.StandardButton.Apply,
            "Reset": QDialogButtonBox.StandardButton.Reset,
            "Help": QDialogButtonBox.StandardButton.Help,
            "RestoreDefaults": QDialogButtonBox.StandardButton.RestoreDefaults,
        },
    )

    # QFileDialog
    patch(
        QFileDialog,
        {
            "ExistingFile": QFileDialog.FileMode.ExistingFile,
            "ExistingFiles": QFileDialog.FileMode.ExistingFiles,
            "Directory": QFileDialog.FileMode.Directory,
            "AnyFile": QFileDialog.FileMode.AnyFile,
            "DontUseNativeDialog": QFileDialog.Option.DontUseNativeDialog,
            "ShowDirsOnly": QFileDialog.Option.ShowDirsOnly,
            "DontResolveSymlinks": QFileDialog.Option.DontResolveSymlinks,
            "DontConfirmOverwrite": QFileDialog.Option.DontConfirmOverwrite,
            "ReadOnly": QFileDialog.Option.ReadOnly,
            "HideNameFilterDetails": QFileDialog.Option.HideNameFilterDetails,
        },
    )

    # QLineEdit
    patch(
        QLineEdit,
        {
            "Normal": QLineEdit.EchoMode.Normal,
            "Password": QLineEdit.EchoMode.Password,
            "NoEcho": QLineEdit.EchoMode.NoEcho,
            "PasswordEchoOnEdit": QLineEdit.EchoMode.PasswordEchoOnEdit,
        },
    )

    # QJsonDocument
    patch(
        QJsonDocument,
        {
            "Compact": QJsonDocument.JsonFormat.Compact,
            "Indented": QJsonDocument.JsonFormat.Indented,
        },
    )

    # QItemSelectionModel
    patch(
        QItemSelectionModel,
        {
            "NoUpdate": QItemSelectionModel.SelectionFlag.NoUpdate,
            "Clear": QItemSelectionModel.SelectionFlag.Clear,
            "Select": QItemSelectionModel.SelectionFlag.Select,
            "Deselect": QItemSelectionModel.SelectionFlag.Deselect,
            "Toggle": QItemSelectionModel.SelectionFlag.Toggle,
            "Current": QItemSelectionModel.SelectionFlag.Current,
            "Rows": QItemSelectionModel.SelectionFlag.Rows,
            "Columns": QItemSelectionModel.SelectionFlag.Columns,
            "SelectCurrent": QItemSelectionModel.SelectionFlag.SelectCurrent,
            "ToggleCurrent": QItemSelectionModel.SelectionFlag.ToggleCurrent,
            "ClearAndSelect": QItemSelectionModel.SelectionFlag.ClearAndSelect,
        },
    )

    # QDialog
    patch(
        QDialog,
        {
            "Accepted": QDialog.DialogCode.Accepted,
            "Rejected": QDialog.DialogCode.Rejected,
        },
    )

    # QFont
    patch(
        QFont,
        {
            # Weight
            "Thin": QFont.Weight.Thin,
            "ExtraLight": QFont.Weight.ExtraLight,
            "Light": QFont.Weight.Light,
            "Normal": QFont.Weight.Normal,
            "Medium": QFont.Weight.Medium,
            "DemiBold": QFont.Weight.DemiBold,
            "Bold": QFont.Weight.Bold,
            "ExtraBold": QFont.Weight.ExtraBold,
            "Black": QFont.Weight.Black,
            # HintingPreference
            "PreferDefaultHinting": QFont.HintingPreference.PreferDefaultHinting,
            "PreferNoHinting": QFont.HintingPreference.PreferNoHinting,
            "PreferVerticalHinting": QFont.HintingPreference.PreferVerticalHinting,
            "PreferFullHinting": QFont.HintingPreference.PreferFullHinting,
            # StyleHint
            "AnyStyle": QFont.StyleHint.AnyStyle,
            "SansSerif": QFont.StyleHint.SansSerif,
            "Serif": QFont.StyleHint.Serif,
            "Monospace": QFont.StyleHint.Monospace,
            "TypeWriter": QFont.StyleHint.TypeWriter,
            # StyleStrategy
            "PreferAntialias": QFont.StyleStrategy.PreferAntialias,
            "NoAntialias": QFont.StyleStrategy.NoAntialias,
            "PreferDefault": QFont.StyleStrategy.PreferDefault,
        },
    )

    # QPainter
    patch(
        QPainter,
        {
            "Antialiasing": QPainter.RenderHint.Antialiasing,
            "TextAntialiasing": QPainter.RenderHint.TextAntialiasing,
            "SmoothPixmapTransform": QPainter.RenderHint.SmoothPixmapTransform,
            "HighQualityAntialiasing": QPainter.RenderHint.Antialiasing,
        },
    )

    # QPalette ColorRole
    patch(
        QPalette,
        {
            "WindowText": QPalette.ColorRole.WindowText,
            "Button": QPalette.ColorRole.Button,
            "Light": QPalette.ColorRole.Light,
            "Midlight": QPalette.ColorRole.Midlight,
            "Dark": QPalette.ColorRole.Dark,
            "Mid": QPalette.ColorRole.Mid,
            "Text": QPalette.ColorRole.Text,
            "BrightText": QPalette.ColorRole.BrightText,
            "ButtonText": QPalette.ColorRole.ButtonText,
            "Base": QPalette.ColorRole.Base,
            "Window": QPalette.ColorRole.Window,
            "Shadow": QPalette.ColorRole.Shadow,
            "Highlight": QPalette.ColorRole.Highlight,
            "HighlightedText": QPalette.ColorRole.HighlightedText,
            "Link": QPalette.ColorRole.Link,
            "LinkVisited": QPalette.ColorRole.LinkVisited,
            "AlternateBase": QPalette.ColorRole.AlternateBase,
            "ToolTipBase": QPalette.ColorRole.ToolTipBase,
            "ToolTipText": QPalette.ColorRole.ToolTipText,
            "PlaceholderText": QPalette.ColorRole.PlaceholderText,
            "NoRole": QPalette.ColorRole.NoRole,
            # ColorGroup
            "Active": QPalette.ColorGroup.Active,
            "Inactive": QPalette.ColorGroup.Inactive,
            "Disabled": QPalette.ColorGroup.Disabled,
            "Normal": QPalette.ColorGroup.Active,  # alias
        },
    )

    # QIODevice
    patch(
        QIODevice,
        {
            "ReadOnly": QIODevice.OpenModeFlag.ReadOnly,
            "WriteOnly": QIODevice.OpenModeFlag.WriteOnly,
            "ReadWrite": QIODevice.OpenModeFlag.ReadWrite,
            "Append": QIODevice.OpenModeFlag.Append,
            "Truncate": QIODevice.OpenModeFlag.Truncate,
            "Text": QIODevice.OpenModeFlag.Text,
            "Unbuffered": QIODevice.OpenModeFlag.Unbuffered,
            "NewOnly": QIODevice.OpenModeFlag.NewOnly,
            "ExistingOnly": QIODevice.OpenModeFlag.ExistingOnly,
        },
    )

    # QEvent
    patch(
        QEvent,
        {
            "ToolTip": QEvent.Type.ToolTip,
            "Enter": QEvent.Type.Enter,
            "Leave": QEvent.Type.Leave,
            "MouseMove": QEvent.Type.MouseMove,
            "MouseButtonPress": QEvent.Type.MouseButtonPress,
            "MouseButtonRelease": QEvent.Type.MouseButtonRelease,
            "MouseButtonDblClick": QEvent.Type.MouseButtonDblClick,
            "KeyPress": QEvent.Type.KeyPress,
            "KeyRelease": QEvent.Type.KeyRelease,
            "FocusIn": QEvent.Type.FocusIn,
            "FocusOut": QEvent.Type.FocusOut,
            "Resize": QEvent.Type.Resize,
            "Close": QEvent.Type.Close,
            "Show": QEvent.Type.Show,
            "Hide": QEvent.Type.Hide,
            "Paint": QEvent.Type.Paint,
            "Wheel": QEvent.Type.Wheel,
            "ContextMenu": QEvent.Type.ContextMenu,
        },
    )

    # QNetworkRequest
    patch(
        QNetworkRequest,
        {
            "ContentTypeHeader": QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "ContentLengthHeader": QNetworkRequest.KnownHeaders.ContentLengthHeader,
            "LocationHeader": QNetworkRequest.KnownHeaders.LocationHeader,
            "LastModifiedHeader": QNetworkRequest.KnownHeaders.LastModifiedHeader,
            "ETagHeader": QNetworkRequest.KnownHeaders.ETagHeader,
            "HttpStatusCodeAttribute": QNetworkRequest.Attribute.HttpStatusCodeAttribute,
            "HttpReasonPhraseAttribute": QNetworkRequest.Attribute.HttpReasonPhraseAttribute,
            "Http2AllowedAttribute": QNetworkRequest.Attribute.Http2AllowedAttribute,
        },
    )
