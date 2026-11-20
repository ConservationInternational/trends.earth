from typing import List


class SpatialSupportedOvertime:
    """Spatial Supported Overtime."""

    year: int
    value: int

    def __init__(self, year, value):
        self.year = year
        self.value = value


class RestorationDataModel:
    """This is for restoration data model."""

    label: str
    target: int
    reported_progress: int
    spatially_supported: int
    spatially_supported_overtime: List[SpatialSupportedOvertime] | None

    # Sub data
    sub_indicator_data: List["RestorationDataModel"]

    def __init__(
        self,
        label: str,
        target,
        reported_progress,
        spatially_supported,
        spatially_supported_overtime=None,
        sub_indicator_data: List["RestorationDataModel"] | None = None,
    ):
        self.label = label
        self.target = target
        self.reported_progress = reported_progress
        self.spatially_supported = spatially_supported
        self.spatially_supported_overtime = spatially_supported_overtime
        self.sub_indicator_data = sub_indicator_data or []


class IndicatorDataModel(RestorationDataModel):
    """Target, reported progress and spatially supported area of indicator,
    as the sum of its sub-indicators."""

    def __init__(
        self,
        label: str,
        sub_indicator_data: List[RestorationDataModel],
    ):
        target = sum(sub.target or 0 for sub in sub_indicator_data)
        reported_progress = sum(
            sub.reported_progress or 0 for sub in sub_indicator_data
        )
        spatially_supported = sum(
            sub.spatially_supported or 0 for sub in sub_indicator_data
        )

        # Spatially supported area per year, summed over the sub-indicators
        overtime_by_year = {}
        for sub in sub_indicator_data:
            for point in sub.spatially_supported_overtime or []:
                overtime_by_year[point.year] = overtime_by_year.get(point.year, 0) + (
                    point.value or 0
                )
        spatially_supported_overtime = [
            SpatialSupportedOvertime(year, value)
            for year, value in sorted(overtime_by_year.items())
        ] or None

        super().__init__(
            label,
            target,
            reported_progress,
            spatially_supported,
            spatially_supported_overtime,
            sub_indicator_data,
        )
