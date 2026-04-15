def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def average(nums):
    if not nums:
        raise ValueError("Cannot average an empty list")
    total = 0
    for n in nums:
        total += n
    return total / len(nums)

if __name__ == "__main__":
    # divide: safe call
    print(divide(10, 2))

    # average: safe call
    print(average([4, 8, 12]))
