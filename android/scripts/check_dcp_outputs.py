"""Independently inspect local Android-kernel outputs with the desktop UDP reader.

All full disc images/extracted files remain in the explicit local work directory.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from retro_trans.dcp import inspect_disc, tree_hash, audio_identity
from retro_trans.core import sha256_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root', type=Path, required=True)
    parser.add_argument('--outputs', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--disc1-dir', type=Path)
    parser.add_argument('--disc2-dir', type=Path)
    args = parser.parse_args()
    if args.work.exists():
        raise ValueError('Preserve prior verification directory.')
    args.work.mkdir(parents=True)
    manifest = json.loads((args.game_root / 'build/automatic-dcp-0.5.20/ready/DCP-AUTOMATIC.json').read_text())
    receipts = []
    for row in manifest['patches']:
        disc = row['metadata']['disc']
        output = getattr(args, f'disc{disc}_dir') or args.outputs / f'disc{disc}-gdi'
        print('Independent UDP inspection, disc', disc, flush=True)
        after = inspect_disc(output / 'disc.gdi', args.work / f'disc{disc}')
        assert tree_hash(after['files']) == row['metadata']['target_tree_sha256']
        assert after['bootsector_invariant_sha256'] == row['metadata']['bootsector_invariant_sha256']
        source_audio = args.game_root / f'Black-Matrix Advanced (Japan) (Disc {disc}) (Track 2).bin'
        assert audio_identity(source_audio) == audio_identity(output / 'track02.raw')
        originals = [args.game_root / f'Black-Matrix Advanced (Japan) (Disc {disc}) (Track {i}).bin' for i in (1, 2, 3)]
        assert [{'bytes': p.stat().st_size, 'sha256': sha256_file(p)} for p in originals] == row['source_tracks']
        receipt = dict(disc=disc, independent_reader='Pinned desktop UDP 2.1.8',
                       target_tree_sha256=tree_hash(after['files']),
                       bootsector_invariant_sha256=after['bootsector_invariant_sha256'],
                       audio_content_and_sample_alignment_preserved=True, originals_unchanged=True)
        receipts.append(receipt)
        print('Independent game-tree/boot/audio/original verification passed.', flush=True)
    (args.work / 'verification.json').write_text(json.dumps(receipts, indent=2) + '\n')


if __name__ == '__main__':
    main()
