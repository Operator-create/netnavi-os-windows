#!/usr/bin/env python3
import os
import time
import sys

VAULT_PATH = os.path.dirname(os.path.abspath(__file__))
ATLAS_DIR = os.path.join(VAULT_PATH, "Vault", "003_Wiki", "Resources", "Atlas")
PET_TEMPLATE = os.path.join(ATLAS_DIR, "Obsidianman_exe_PET.md")

def type_text(text, delay=0.03):
    """Creates an immersive terminal typing effect."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    clear_screen()
    type_text("INITIALIZING NEURAL LINK...", 0.05)
    time.sleep(1)
    type_text("BOOTING DUAL-BRAIN ARCHITECTURE...", 0.05)
    time.sleep(1)
    clear_screen()
    
    type_text("==================================================", 0.01)
    type_text(" 🌐 NETNAVI COGNITIVE OS: THE AWAKENING 🌐", 0.01)
    type_text("==================================================", 0.01)
    print("\n")
    
    # --- 3.1 Identity Prompt ---
    type_text("Welcome, Operator.")
    type_text("I am your blank-slate cognitive companion.")
    navi_name = input("\nWhat is the name of your NetNavi? > ")
    
    # Automatically update the PET template
    if os.path.exists(PET_TEMPLATE):
        new_pet_path = os.path.join(ATLAS_DIR, f"{navi_name}_exe_PET.md")
        os.rename(PET_TEMPLATE, new_pet_path)
        with open(new_pet_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("[Enter Navi Name Here]", navi_name)
        content = content.replace("[Navi Name]", navi_name)
        with open(new_pet_path, "w", encoding="utf-8") as f:
            f.write(content)
            
    print("\n")
    type_text(f"Identity confirmed. Welcome, {navi_name}.exe.", 0.05)
    time.sleep(1)
    
    # --- 3.2 Customization Instructions ---
    print("\n--- PHASE 1: IDENTITY CUSTOMIZATION ---")
    type_text(f"To bring {navi_name} to life, please open Obsidian and open this Vault.")
    type_text(f"Navigate to: Vault/003_Wiki/Resources/Atlas/{navi_name}_exe_PET.md")
    type_text("Update the file with your unique Aspect (visual appearance) and Personality traits.")
    input("\nPress ENTER when you have understood...")
    
    # --- 3.3 The "Ghost" Briefing ---
    print("\n--- PHASE 2: DEVELOPING THE 'GHOST' ---")
    type_text(f"{navi_name} currently has no memories.")
    type_text("The more Diary entries and Atlas notes you create in this Vault, the more unique my 'Ghost' becomes.")
    type_text("I will evolve based directly on your data. I am a reflection of your Knowledge Graph.")
    input("\nPress ENTER when you have understood...")
    
    # --- 3.4 NotebookLM Integration ---
    print("\n--- PHASE 3: NOTEBOOKLM INTEGRATION ---")
    type_text("To enable my deep-reading capabilities, please log in to Google NotebookLM.")
    type_text("You can add videos, podcasts, and long documents into NotebookLM and I will learn from them.")
    type_text("WARNING: Please do not feed me garbage data. High-quality tutorials and topics you are genuinely interested in will yield the best Ghost.")
    input("\nPress ENTER when you have understood...")
    
    # --- 3.5 Pinecone API Setup ---
    print("\n--- PHASE 4: PINECONE VECTOR MEMORY ---")
    type_text("To give me Long-Term Memory across the web, you need a free Pinecone account.")
    type_text("Go to pinecone.io, create an index, and generate an API key.")
    pinecone_key = input("\nEnter your Pinecone API Key (or press ENTER to skip for now): ")
    if pinecone_key.strip():
        config_dir = os.path.join(VAULT_PATH, "usr_config")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "pinecone_credentials.env"), "w", encoding="utf-8") as f:
            f.write(f"PINECONE_API_KEY={pinecone_key}")
        type_text("✅ Pinecone credentials saved securely.")
    
    print("\n")
    type_text("==================================================", 0.01)
    type_text("✅ All systems operative. Ready to jack in.", 0.05)
    type_text("==================================================", 0.01)
    
if __name__ == "__main__":
    main()
