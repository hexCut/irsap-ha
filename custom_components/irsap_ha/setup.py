async def async_setup(hass, config):
    """Imposta le piattaforme clima e sensore."""

    # Non passare async_add_entities qui, viene gestito in async_setup_entry
    return True
