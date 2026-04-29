import sys


def count_words(filename):
    try:
        with open(filename) as f:
            content = f.read()
        words = content.split()
        return len(words)
    except FileNotFoundError:
        print(f"Error: file '{filename}' not found", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: word_counter.py <filename>", file=sys.stderr)
        sys.exit(1)
    print(count_words(sys.argv[1]))
