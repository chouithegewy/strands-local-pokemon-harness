"""Derive walkability from the user's checksum-verified ROM (no graphics copied)."""
import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAPS = [
    (0, 'PalletTown', 10, 9, 'Overworld'),
    (1, 'ViridianCity', 20, 18, 'Overworld'),
    (12, 'Route1', 10, 18, 'Overworld'),
    (37, 'RedsHouse1F', 4, 4, 'RedsHouse1'),
    (38, 'RedsHouse2F', 4, 4, 'RedsHouse2'),
    (40, 'OaksLab', 5, 6, 'Dojo'),
    (41, 'ViridianPokecenter', 7, 4, 'Pokecenter'),
    (42, 'ViridianMart', 4, 4, 'Mart'),
]


def build(rom_path, symbols_path):
    rom = Path(rom_path).read_bytes()
    symbols = {}
    for line in Path(symbols_path).read_text().splitlines():
        address, name = line.split()
        bank, addr = [int(value, 16) for value in address.split(':')]
        symbols[name] = bank * 0x4000 + (addr & 0x3fff)

    output = {}
    for map_id, name, width, height, tiles in MAPS:
        pointer = symbols[tiles + '_Coll']
        collision = []
        while rom[pointer] != 255:
            collision.append(rom[pointer])
            pointer += 1
        blocks = symbols[name + '_Blocks']
        blockset = symbols[tiles + '_Block']
        walk = []
        for y in range(height * 2):
            row = []
            for x in range(width * 2):
                block = rom[blocks + (y // 2) * width + x // 2]
                tile = rom[blockset + block * 16 + (y % 2) * 8 + (x % 2) * 2 + 4]
                row.append(int(tile in collision))
            walk.append(row)
        if not any(value for row in walk for value in row):
            raise ValueError(f'No walkable tiles for {name}; verify the map header tileset')
        output[map_id] = dict(name=name, width=width * 2, height=height * 2, walk=walk)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--symbols', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'game_assets/maps.json')
    args = parser.parse_args()
    output = build(args.rom, args.symbols)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output))
    print('Derived walkability for', len(output), 'maps at', args.output)


if __name__ == '__main__':
    main()
