"""A yes/no button prompt that only the person who ran the command can click."""
import discord


class Confirm(discord.ui.View):
    def __init__(self, user_id: int, confirm_label: str = "yes, do it"):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.value: bool | None = None
        self.confirm.label = confirm_label

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="yes", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = True
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = False
        await interaction.response.edit_message(content="cancelled, nothing changed.", view=None)
        self.stop()


async def ask(interaction: discord.Interaction, question: str, confirm_label: str) -> bool:
    """Sends a private confirmation prompt; returns True only if they clicked the confirm button."""
    view = Confirm(interaction.user.id, confirm_label)
    await interaction.response.send_message(question, view=view, ephemeral=True)
    await view.wait()
    if view.value is None:
        await interaction.edit_original_response(content="timed out, nothing changed.", view=None)
    return bool(view.value)
