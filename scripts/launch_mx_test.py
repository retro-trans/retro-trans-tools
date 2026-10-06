"""Local MX test build: opens the converter, without startup scans or updates."""
import sys

from retro_trans.gui import Application
from launch import diagnose


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--health-check':
        sys.exit(diagnose(sys.argv[2]))
    app = Application(startup=False)
    app.title(app.title() + ' — MX converter test')
    app.app_update_status = 'Local MX experimental build. No startup update check.'
    app.notebook.select(2)
    app.save_game.set('MX (experimental)')
    app.mainloop()
