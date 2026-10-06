"""Installation reminders; never modify a console or emulator installation."""
from pathlib import Path

INSTALLATION_WARNING = (
    'Before playing the patched PS3 game, delete its previous installation data '
    'so the game rebuilds it from the patched files. Close the game or emulator first.\n\n'
    'Remove only this game\'s installed data/cache. Keep your saved games and game image.\n\n'
    'PS3: use Game Data Utility, not Saved Data Utility.\n'
    'RPCS3: remove only the related installation-data folder under dev_hdd0/game '
    '(for SRW Z3 Jigoku-hen: BLJS10256_DATA). Keep other games and savedata.'
)
MANUAL_REMINDER = 'PS3 games: delete the old installation data before playing; keep your saves.'


def is_ps3_platform(platform):
    return ''.join(c for c in platform.casefold() if c.isalnum()) in (
        'ps3', 'playstation3', 'sonyplaystation3')


def looks_like_ps3(source):
    """Bounded hints for manual patches, which need no catalog identity."""
    path = Path(source)
    if any(p.name.upper() == 'PS3_GAME' for p in (path, *path.parents)):
        return True
    if (path / 'PS3_GAME').is_dir():
        return True
    try:
        with path.open('rb') as stream:
            stream.seek(16 * 2048)
            descriptor = stream.read(2048)
        return (descriptor[:7] == b'\x01CD001\x01' and
                (descriptor[40:72].rstrip(b' \0') == b'PS3VOLUME' or
                 descriptor[8:40].rstrip(b' \0') == b'PLAYSTATION3'))
    except OSError:
        return False
