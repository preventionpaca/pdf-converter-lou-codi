from lou_codi_pdf_converter.services.cutting_optimizer import Part, Sheet, optimize_cutting


def test_optimizer_places_rectangles_and_respects_kerf() -> None:
    plan = optimize_cutting(
        [Sheet(1, "Panneau", 100, 60)],
        [Part("A", 45, 60), Part("B", 45, 60)],
        kerf=5,
    )

    assert len(plan.sheets) == 1
    assert [item.label for item in plan.sheets[0].placements] == ["A", "B"]
    assert plan.unplaced == []
    first, second = plan.sheets[0].placements
    assert second.x >= first.x + first.width + 5


def test_optimizer_can_rotate_a_part_and_report_an_unplaced_part() -> None:
    plan = optimize_cutting(
        [Sheet(4, "Chute", 80, 50)],
        [Part("Pivotée", 45, 70), Part("Trop grande", 200, 200)],
        kerf=3,
    )

    assert plan.sheets[0].placements[0].rotated is True
    assert plan.sheets[0].placements[0].width == 70
    assert [item.label for item in plan.unplaced] == ["Trop grande"]
