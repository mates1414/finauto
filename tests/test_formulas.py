from finauto.engine.formulas import a1, blank_guard, col, iferror, sref


def test_col():
    assert col(0) == "A"
    assert col(11) == "L"
    assert col(1, abs_col=True) == "$B"


def test_a1():
    assert a1(0, 0) == "A1"
    assert a1(4, 1) == "B5"
    assert a1(4, 1, abs_row=True, abs_col=True) == "$B$5"
    assert a1(20, 1, abs_row=True) == "B$21"


def test_sref():
    assert sref("04_DCF_Model", "B5") == "'04_DCF_Model'!B5"


def test_iferror():
    assert iferror("A1/B1") == 'IFERROR(A1/B1,"")'
    assert iferror("A1/B1", "0") == "IFERROR(A1/B1,0)"


def test_blank_guard_single():
    assert blank_guard(["A1"], "A1*2") == 'IF(A1="","",IFERROR(A1*2,""))'


def test_blank_guard_multi():
    got = blank_guard(["A1", "B1"], "A1/B1")
    assert got == 'IF(OR(A1="",B1=""),"",IFERROR(A1/B1,""))'
