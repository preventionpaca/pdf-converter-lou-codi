from lou_codi_pdf_converter.services.table_formulas import evaluate_table


def test_table_arithmetic_and_percentage() -> None:
    result = evaluate_table("10\t5\t=A1+B1\n20\t=A2*10%\t=A2-B2")
    assert result == [["10", "5", "15"], ["20", "2", "18"]]


def test_table_sum_and_invalid_formula() -> None:
    result = evaluate_table("2\n3\n=SUM(A1:A2)\n=1/0")
    assert result == [["2"], ["3"], ["5"], ["#ERREUR"]]
