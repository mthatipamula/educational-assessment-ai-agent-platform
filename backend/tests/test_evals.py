from app.evals import quadratic_weighted_kappa


def test_qwk_perfect_and_chance_and_ordering():
    assert quadratic_weighted_kappa([0, 1, 2, 3, 4], [0, 1, 2, 3, 4], 0, 4) == 1.0
    off_by_one = quadratic_weighted_kappa([0, 1, 2, 3, 4], [1, 2, 3, 4, 4], 0, 4)
    far_off = quadratic_weighted_kappa([0, 1, 2, 3, 4], [4, 3, 2, 1, 0], 0, 4)
    assert 0.5 < off_by_one < 1.0   # small disagreements cost little
    assert far_off < 0               # systematic reversal is worse than chance
