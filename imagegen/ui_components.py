# pylint: disable=too-many-arguments, too-many-positional-arguments, unused-argument
"""UI components for image generation interactions in Discord."""

import uuid
from discord import ui, ButtonStyle, Interaction


class AcceptRetryDeleteButtons(ui.View):
    """View containing Accept, Try Again, and Delete buttons for image generation."""

    LABEL_TRY_AGAIN = "Try Again"
    LABEL_DRAWING = "Drawing..."

    def __init__(self, cog, ctx, task_id, payload, message, timeout=60):
        """
        Initialize the button view.

        Args:
            cog: Reference to the parent Cog.
            ctx: The command context.
            task_id: The current task identifier.
            payload: The generation payload.
            message: The Discord message being interacted with.
            timeout: Auto-disable timeout in seconds.
        """
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.task_id = task_id
        self.payload = payload
        self.message = message

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Restrict interaction to the original message author."""
        if interaction.user == self.ctx.author:
            return True
        await interaction.response.send_message(
            "You are not allowed to interact with these buttons.",
            ephemeral=True
        )
        return False

    @ui.button(label="Accept", style=ButtonStyle.green)
    async def accept(self, interaction: Interaction, button: ui.Button):
        """Accept the generated image and disable the UI."""
        self.clear_items()
        await interaction.response.edit_message(content="", view=self)
        self.stop()

    @ui.button(label="Try Again", style=ButtonStyle.primary)
    async def try_again(self, interaction: Interaction, button: ui.Button):
        """Retry the image generation with the same payload."""
        if not await self.interaction_check(interaction):
            return

        button.label = self.LABEL_DRAWING
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(view=self)
        new_task_id = uuid.uuid4().hex
        await self.cog.retry_task(new_task_id, self)

    @ui.button(label="Delete", style=ButtonStyle.danger)
    async def delete(self, interaction: Interaction, button: ui.Button):
        """Delete the image message and stop the interaction."""
        if not await self.interaction_check(interaction):
            return

        await interaction.message.delete()
        self.stop()

    async def on_timeout(self):
        """Auto-disable view after timeout by clearing items."""
        self.clear_items()
        await self.message.edit(content="", view=None)
