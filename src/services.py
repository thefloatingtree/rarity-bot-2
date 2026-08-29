from derpibooru import Search

from config import firebase_db


def search_derpi(tags: list[str]) -> str:
    for image in Search().query("safe", *tags).sort_by("random").limit(1):
        return image.medium

    return "No images matching query: " + ", ".join(tags)


async def get_firebase_value(
    collection_name: str, document_name: str, field_name: str, default_value
):
    # Ensure value exists in firebase
    document_ref = firebase_db.collection(collection_name).document(document_name)
    document = await document_ref.get()
    value = document.get(field_name)
    if value == None:
        await document_ref.set({field_name: default_value})
        value = default_value
    return value


def author_fields(user) -> dict:
    """The ownership stamp to store on a user-created resource."""
    return {"author_id": str(user.id)}


def author_reference(data: dict) -> str:
    """Render a stored resource's owner as a mention, so the shown name is
    always current. Falls back to the legacy username snapshot for documents
    written before ids were stored."""
    author_id = data.get("author_id")
    if author_id:
        return f"<@{author_id}>"
    return data.get("author") or "someone"


def display_name(user, member=None) -> str:
    """A human readable name for display only -- never store or match on it."""
    if member is not None:
        return member.display_name
    return user.global_name or user.username
