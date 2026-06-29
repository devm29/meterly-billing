from typing import Annotated

from pydantic import Field

Slug = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
