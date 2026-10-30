from launcher import engine


def test_scan_and_command(tmp_path):
    (tmp_path / "a.iso").write_bytes(b"x")
    (tmp_path / "n.txt").write_bytes(b"x")
    assert [p.name for p in engine.scan_games(str(tmp_path))] == ["a.iso"]
    cmd = engine.build_command("pcsx2-qt", "a.iso", bios="b.bin")
    assert cmd[-2:] == ["--", "a.iso"] and "-bios" in cmd
    assert "-elf" in engine.build_command("pcsx2-qt", "h.elf")
