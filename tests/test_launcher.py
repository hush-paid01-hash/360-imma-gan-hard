from launcher import engine


def test_scan_and_command(tmp_path):
    (tmp_path / "a.iso").write_bytes(b"x")
    (tmp_path / "n.txt").write_bytes(b"x")
    assert [p.name for p in engine.scan_games(str(tmp_path))] == ["a.iso"]
    cmd = engine.build_command("pcsx2-qt", "a.iso", bios="b.bin")
    assert cmd[-2:] == ["--", "a.iso"] and "-bios" not in cmd
    assert "-elf" in engine.build_command("pcsx2-qt", "h.elf")


def test_filter_and_recent(tmp_path):
    from pathlib import Path
    g = [Path("/g/Alpha.iso"), Path("/g/Beta.iso")]
    assert engine.filter_games(g, "alp") == [g[0]]
    assert engine.filter_games(g, view="favorites", favorites=["/g/Beta.iso"]) == [g[1]]
    assert engine.filter_games(g, view="recent", recent=["/g/Beta.iso", "/g/Alpha.iso"]) == [g[1], g[0]]
    assert engine.push_recent(["a", "b"], "b") == ["b", "a"]
