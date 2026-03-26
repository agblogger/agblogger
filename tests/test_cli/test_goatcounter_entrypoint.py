from pathlib import Path


def test_entrypoint_reprovisions_when_db_volume_is_replaced_but_token_volume_remains() -> None:
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()

    assert 'if [ ! -f "$TOKEN_FILE" ] || [ ! -s "$GOATCOUNTER_DB" ]; then' in entrypoint
