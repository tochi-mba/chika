# Small user API — refactored
from typing import Optional


class UserAPI:
    def __init__(self) -> None:
        self._users: list[dict[str, str]] = []

    def add(self, name: str, email: str) -> None:
        self._users.append({"name": name, "email": email})

    def find(self, name: str) -> Optional[dict[str, str]]:
        for user in self._users:
            if user["name"] == name:
                return user
        return None

    def remove(self, name: str) -> None:
        self._users = [user for user in self._users if user["name"] != name]

    def count(self) -> int:
        return len(self._users)


if __name__ == "__main__" or True:
    api = UserAPI()
    api.add("alice", "a@b.c")
    api.add("bob", "b@c.d")
    print(api.find("alice"))
    print(api.count())
