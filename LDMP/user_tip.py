"""User tip widget."""

from qgis.PyQt.QtWidgets import (
    QLabel,
    QSizePolicy,
    QToolTip
)

from .utils import FileUtils


class UserTip(QLabel):
    """
    Custom label that shows an information icon and a tip containing the
    column user tip value.
    """

    def __init__(self, parent=None, user_tip=None):
        super().__init__(parent)

        # Set size policy
        self.setSizePolicy(
            QSizePolicy(
                QSizePolicy.Fixed,
                QSizePolicy.Fixed
            )
        )

        self.setMouseTracking(True)

        # Set tip icon
        self._set_tip_icon()

        # Customize appearance of the tooltip
        self.setStyleSheet(
            'QToolTip { color: #ffffff; background-color: #2a82da; '
            'border: 1px solid white; }'
        )

        # Initialize user tip
        if user_tip is None:
            self._user_tip = ''
        else:
            self._user_tip = user_tip

    def _set_tip_icon(self):
        # Set the information icon
        self._px = FileUtils.get_icon_pixmap('user_tip.png')
        self.setPixmap(self._px)

    def pixmap(self):
        """
        :return: Returns the pixmap object associated with this label.
        Overrides the default implementation.
        :rtype: QPixmap
        """
        return self._px

    def mouseMoveEvent(self, event):
        """
        Override so that the tool tip can be shown immediately.
        :param event: Mouse move event
        :type event: QMouseEvent
        """
        QToolTip.showText(
            event.globalPos(), self._user_tip, self
        )

    @property
    def user_tip(self):
        """
        :return: Returns the user tip corresponding to this label.
        :rtype: str
        """
        return self._user_tip

    @user_tip.setter
    def user_tip(self, value):
        """
        Sets the user tip for this label.
        :param value: User tip text.
        :type value: str
        """
        if not value:
            return

        self._user_tip = value