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
