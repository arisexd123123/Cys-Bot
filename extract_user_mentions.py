
import json

# Load ticket stats
with open('ticket_stats.json', 'r') as f:
    ticket_stats = json.load(f)

# Format user IDs as mentions
for user_id in ticket_stats.keys():
    mention = f"<@{user_id}>"
    print(f"User ID: {user_id} → Mention format: {mention}")

# Example of how to use these mentions in other code
print("\nExample usage in code:")
print("await ctx.send(f\"Stats for {mention}\")")
