from flask import render_template, redirect, url_for, request, flash, session
from app import app, db
from flask_login import login_user, logout_user, login_required, current_user, UserMixin
from flask_bcrypt import Bcrypt
from bson.objectid import ObjectId

bcrypt = Bcrypt(app)

# ─────────────────────────────────────────────
# USER MODEL
# ─────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.username = user_data["username"]
        self.email = user_data["email"]
        self.points = user_data.get("points", 0)
        self.level = user_data.get("level", "Beginner Cook")
        self.badges = user_data.get("badges", [])
        self.favorites = user_data.get("favorites", [])
        self.is_admin = user_data.get("is_admin", False)

from app import login_manager

@login_manager.user_loader
def load_user(user_id):
    user_data = db.users.find_one({"_id": ObjectId(user_id)})
    if user_data:
        return User(user_data)
    return None

# ─────────────────────────────────────────────
# HOME
# ─────────────────────────────────────────────
from datetime import datetime

def log_activity(action_type, username, details=""):
    """Records a user activity event for admin statistics."""
    try:
        db.activity_logs.insert_one({
            "action_type": action_type,  # "login", "search", "cooked", "register"
            "username": username,
            "details": details,
            "timestamp": datetime.now(),
            "date": datetime.now().strftime("%Y-%m-%d")
        })
    except Exception as e:
        print(f"Activity log error: {e}")

# ─────────────────────────────────────────────
# CHALLENGE TEMPLATES (the pool to pick from)
# ─────────────────────────────────────────────

CHALLENGE_POOL = [
    {"id": "cook_3_pork", "title": "Pork Lover", "description": "Cook 3 Pork dishes this week", "type": "category_count", "category": "Pork", "target": 3, "points": 50},
    {"id": "cook_3_chicken", "title": "Chicken Champion", "description": "Cook 3 Chicken dishes this week", "type": "category_count", "category": "Chicken", "target": 3, "points": 50},
    {"id": "cook_3_seafood", "title": "Seafood Specialist", "description": "Cook 3 Seafood dishes this week", "type": "category_count", "category": "Seafood", "target": 3, "points": 50},
    {"id": "cook_3_vegetable", "title": "Veggie Victory", "description": "Cook 3 Vegetable dishes this week", "type": "category_count", "category": "Vegetable", "target": 3, "points": 50},
    {"id": "budget_saver", "title": "Budget Saver", "description": "Cook 3 recipes that cost ₱150 or less", "type": "budget_count", "max_cost": 150, "target": 3, "points": 60},
    {"id": "try_new", "title": "Adventurous Cook", "description": "Cook 2 recipes you've never cooked before", "type": "new_recipes", "target": 2, "points": 40},
    {"id": "cook_5_total", "title": "Kitchen Warrior", "description": "Cook 5 recipes this week, any kind", "type": "total_count", "target": 5, "points": 70},
    {"id": "soup_lover", "title": "Soup Season", "description": "Cook 2 Soup dishes this week", "type": "category_count", "category": "Soup", "target": 2, "points": 45},
]

import random

def get_current_week_id():
    """Returns a string like '2026-W25' representing the current ISO week."""
    now = datetime.now()
    year, week, _ = now.isocalendar()
    return f"{year}-W{week}"


def get_weekly_challenges():
    """Gets (or creates) this week's 3 active challenges, deterministically seeded by week."""
    week_id = get_current_week_id()

    existing = db.weekly_challenges.find_one({"week_id": week_id})
    if existing:
        return existing["challenges"]

    # Deterministic random selection so it's the same for everyone, but changes weekly
    random.seed(week_id)
    selected = random.sample(CHALLENGE_POOL, 3)

    db.weekly_challenges.insert_one({
        "week_id": week_id,
        "challenges": selected,
        "created_at": datetime.now()
    })

    return selected


def get_user_challenge_progress(user_id, challenges):
    """Calculates how far along the user is on each of this week's challenges."""
    week_id = get_current_week_id()
    now = datetime.now()
    year, week, _ = now.isocalendar()

    # Get start of this ISO week (Monday)
    week_start = datetime.fromisocalendar(year, week, 1)

    user_data = db.users.find_one({"_id": ObjectId(user_id)})
    cooking_history = user_data.get("cooking_history", [])

    # Filter to only this week's cooking activity
    this_week_cooks = []
    for entry in cooking_history:
        try:
            cook_date = datetime.strptime(entry["date"], "%Y-%m-%d %H:%M")
            if cook_date >= week_start:
                this_week_cooks.append(entry)
        except (ValueError, KeyError):
            continue

    progress_list = []

    for challenge in challenges:
        progress = 0

        if challenge["type"] == "total_count":
            progress = len(this_week_cooks)

        elif challenge["type"] == "category_count":
            # Need to look up each recipe's category
            count = 0
            for entry in this_week_cooks:
                recipe = db.recipes.find_one({"name": {"$regex": f"^{entry['name']}$", "$options": "i"}})
                if recipe and recipe.get("category") == challenge["category"]:
                    count += 1
            progress = count

        elif challenge["type"] == "budget_count":
            count = 0
            for entry in this_week_cooks:
                recipe = db.recipes.find_one({"name": {"$regex": f"^{entry['name']}$", "$options": "i"}})
                if recipe:
                    cost_str = recipe.get("estimated_total_cost", "₱999")
                    digits = "".join(c for c in cost_str if c.isdigit())
                    cost = int(digits) if digits else 999
                    if cost <= challenge["max_cost"]:
                        count += 1
            progress = count

        elif challenge["type"] == "new_recipes":
            # Count unique recipe names cooked this week that weren't cooked before this week
            before_week_names = set()
            for entry in cooking_history:
                try:
                    cook_date = datetime.strptime(entry["date"], "%Y-%m-%d %H:%M")
                    if cook_date < week_start:
                        before_week_names.add(entry["name"].lower())
                except (ValueError, KeyError):
                    continue

            new_names = set()
            for entry in this_week_cooks:
                if entry["name"].lower() not in before_week_names:
                    new_names.add(entry["name"].lower())
            progress = len(new_names)

        completed = progress >= challenge["target"]

        # Check if already claimed
        claim_key = f"{week_id}_{challenge['id']}"
        already_claimed = claim_key in user_data.get("claimed_challenges", [])

        progress_list.append({
            **challenge,
            "progress": min(progress, challenge["target"]),
            "completed": completed,
            "claimed": already_claimed,
            "claim_key": claim_key
        })

    return progress_list

@app.route("/")
def home():
    return redirect(url_for("login"))

# ─────────────────────────────────────────────
# REGISTER
# ─────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        # Check if email already exists
        existing_user = db.users.find_one({"email": email})
        if existing_user:
            flash("Email already registered. Please log in.", "danger")
            return redirect(url_for("register"))

        # Hash the password
        hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")

        # Save user to MongoDB
        db.users.insert_one({
            "username": username,
            "email": email,
            "password": hashed_pw,
            "points": 0,
            "level": "Beginner Cook",
            "badges": [],
            "favorites": [],
            "cooking_history": []
        })

        log_activity("register", username, f"New account created: {email}")
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user_data = db.users.find_one({"email": email})

        if user_data and bcrypt.check_password_hash(user_data["password"], password):
            user = User(user_data)
            login_user(user)

            flash("Welcome back!", "success")

            if user.is_admin:
                return redirect(url_for("admin_dashboard"))

            return redirect(url_for("dashboard"))

        else:
            flash("Invalid email or password.", "danger")

    return render_template("login.html")

# ─────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))

# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard(): 
    user_data = db.users.find_one({"_id": ObjectId(current_user.id)})
    return render_template("dashboard.html", user=user_data)

# ─────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────

import base64

@app.route("/profile")
@login_required
def profile():
    user_data = db.users.find_one({"_id": ObjectId(current_user.id)})
    return render_template("profile.html", user=user_data)


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        username = request.form.get("username")
        update_data = {"username": username}

        # Handle profile picture upload
        if "profile_picture" in request.files:
            file = request.files["profile_picture"]
            if file and file.filename != "":
                # Limit file size to 2MB
                file.seek(0, 2)
                file_size = file.tell()
                file.seek(0)

                if file_size > 2 * 1024 * 1024:
                    flash("Image too large. Please choose an image under 2MB.", "danger")
                    return redirect(url_for("edit_profile"))

                # Convert image to base64
                image_data = base64.b64encode(file.read()).decode("utf-8")
                mime_type = file.content_type  # e.g. image/png, image/jpeg
                update_data["profile_picture"] = f"data:{mime_type};base64,{image_data}"

        db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": update_data}
        )
        flash("Profile updated successfully!", "success")
        return redirect(url_for("profile"))

    user_data = db.users.find_one({"_id": ObjectId(current_user.id)})
    return render_template("edit_profile.html", user=user_data)

from groq import Groq
import os
import json

# Configure Groq
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ─────────────────────────────────────────────
# MEAL PREFERENCE INPUT
# ─────────────────────────────────────────────

@app.route("/recommend", methods=["GET", "POST"])
@login_required
def recommend():
    if request.method == "POST":
        budget = request.form.get("budget")
        preferred_dish = request.form.get("preferred_dish")
        household_size = request.form.get("household_size")
        meal_type = request.form.get("meal_type")

        # Store inputs in session to use in results page
        session["budget"] = budget
        session["preferred_dish"] = preferred_dish
        session["household_size"] = household_size
        session["meal_type"] = meal_type

        log_activity("search", current_user.username, preferred_dish)

        return redirect(url_for("recommend_results"))

    return render_template("recommend.html")


# ─────────────────────────────────────────────
# AI RECIPE RECOMMENDATIONS RESULTS
# ─────────────────────────────────────────────

@app.route("/recommend/results")
@login_required
def recommend_results():
    budget = session.get("budget")
    preferred_dish = session.get("preferred_dish")
    household_size = session.get("household_size")
    meal_type = session.get("meal_type", "Any")

    if not budget or not preferred_dish or not household_size:
        flash("Please fill in all fields.", "danger")
        return redirect(url_for("recommend"))

    budget_num = int(budget)

    # ==========================
    # STEP 1: SEARCH MONGODB FIRST
    # ==========================
    database_results = []

    try:
        db_recipes = db.recipes.find({
            "$or": [
                {"name": {"$regex": preferred_dish, "$options": "i"}},
                {"description": {"$regex": preferred_dish, "$options": "i"}},
                {"category": {"$regex": f"^{preferred_dish}$", "$options": "i"}},
                {"tags": {"$regex": preferred_dish, "$options": "i"}}
            ]
        })

        for recipe in db_recipes:
            database_results.append({
                "name": recipe.get("name"),
                "description": recipe.get("description"),
                "estimated_cost": recipe.get("estimated_total_cost", "₱0"),
                "prep_time": recipe.get("prep_time", "N/A"),
                "cook_time": recipe.get("cook_time", "N/A"),
                "servings": recipe.get("servings", household_size),
                "ingredients": recipe.get("ingredients", []),
                "instructions": recipe.get("instructions", []),
                "tips": recipe.get("tips", ""),
                "category": recipe.get("category", "Other"),
                "tags": recipe.get("tags", []),
                "source": "database"
            })

    except Exception as e:
        print("MongoDB Search Error:", e)

    # ==========================
    # STEP 2: AI RECOMMENDATIONS — FULL DETAIL IN ONE CALL
    # ==========================
    ai_recipes = []
    remaining_slots = max(4 - len(database_results), 1)

    try:
        prompt = f"""
You are a Filipino recipe assistant. A user wants Filipino recipe recommendations.

User Input:
- Budget: ₱{budget}
- Preferred Dish, Ingredient, or Category: {preferred_dish}
- Household Size: {household_size} persons
- Meal Type: {meal_type}

STRICT RULES:
1. "{preferred_dish}" could be a SPECIFIC DISH NAME, an INGREDIENT, or a FOOD CATEGORY.
2. If it is a specific dish name, only recommend VARIATIONS of that dish.
3. If it is an ingredient, recommend dishes that use that ingredient as the main component.
4. If it is a category (Pork, Chicken, Beef, Seafood, Vegetable, Soup, Noodles, Snack), recommend a DIVERSE mix of dishes in that category.
5. Each recipe's TOTAL cost must not exceed ₱{budget}.
6. Suggest exactly {remaining_slots} recipes.
7. Use these REAL reference prices per kilo as your baseline — do not invent unrealistic numbers: Chicken ₱180-220, Pork ₱280-320, Beef ₱380-450, Shrimp ₱320-450, Bangus/Milkfish ₱180-220, Tilapia ₱120-150, Rice ₱50-60, common vegetables (eggplant, okra, sitaw, kangkong) ₱40-80 per bundle/kilo, onions/garlic/tomatoes ₱80-150 per kilo, soy sauce/vinegar ₱15-30 per bottle.
8. Scale ALL ingredient quantities and prices specifically for {household_size} serving(s) — do not default to 4-6 servings.
9. The "estimated_cost" field MUST exactly equal the sum of all ingredient "estimated_price" values. Calculate this carefully before responding.
10. Category MUST be exactly one of: Pork, Chicken, Beef, Seafood, Vegetable, Soup, Noodles, Snack, Other. Provide 2-4 relevant lowercase tags.
11. Include full ingredients list and complete step-by-step instructions for EACH recipe.

Respond ONLY in JSON, no extra text:

{{
  "recipes": [
    {{
      "name": "Recipe Name",
      "description": "Short description",
      "estimated_cost": "₱XXX",
      "prep_time": "XX mins",
      "cook_time": "XX mins",
      "servings": "{household_size}",
      "category": "Pork, Chicken, Beef, Seafood, Vegetable, Soup, Noodles, Snack, or Other",
      "tags": ["tag1", "tag2"],
      "ingredients": [
        {{
          "name": "Ingredient Name",
          "quantity": "amount for {household_size} serving(s)",
          "estimated_price": "₱XXX"
        }}
      ],
      "instructions": [
        "Step 1: Do this first.",
        "Step 2: Do this next.",
        "Step 3: Continue cooking.",
        "Step 4: Final step."
      ],
      "tips": "Optional cooking tip here."
    }}
  ]
}}
"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )

        response_text = response.choices[0].message.content.strip()

        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        data = json.loads(response_text)
        raw_ai_recipes = data.get("recipes", [])

        for r in raw_ai_recipes:
            r["source"] = "ai"
            if "category" not in r or not r["category"]:
                r["category"] = "Other"
            if "tags" not in r or not r["tags"]:
                r["tags"] = []
            ai_recipes.append(r)

    except Exception as e:
        print(f"Groq error: {e}")
        if not database_results:
            flash("AI recommendation failed. Please try again.", "danger")

    # ==========================
    # STEP 3: MERGE & REMOVE DUPLICATES
    # ==========================
    seen = set()
    all_recipes = []

    for recipe in database_results + ai_recipes:
        recipe_name = recipe.get("name", "").lower()
        if recipe_name not in seen:
            seen.add(recipe_name)
            all_recipes.append(recipe)

    # ==========================
    # STEP 4: RANK BY AFFORDABILITY AND RELEVANCE
    # ==========================
    def extract_cost(recipe):
        cost_str = recipe.get("estimated_cost", "0")
        digits = "".join(c for c in cost_str if c.isdigit())
        return int(digits) if digits else 0

    def relevance_score(recipe):
        name = recipe.get("name", "").lower()
        category = recipe.get("category", "").lower()
        search_term = preferred_dish.lower()

        if name.startswith(search_term):
            return 3
        elif search_term in name:
            return 2
        elif category == search_term:
            return 1
        return 0

    for r in all_recipes:
        r["_cost_value"] = extract_cost(r)
        r["_relevance"] = relevance_score(r)
        r["_within_budget"] = 1 if r["_cost_value"] <= budget_num else 0

    all_recipes = sorted(
        all_recipes,
        key=lambda r: (-r["_within_budget"], -r["_relevance"], r["_cost_value"])
    )

    # Store full recipe data so recipe_detail can reuse it instead of regenerating
    session["last_search_recipes"] = all_recipes

    return render_template("recommend_results.html",
                           recipes=all_recipes,
                           budget=budget,
                           preferred_dish=preferred_dish,
                           household_size=household_size,
                           meal_type=meal_type)
# ─────────────────────────────────────────────
# RECIPE DETAIL
# ─────────────────────────────────────────────

@app.route("/recipe/<recipe_name>")
@login_required
def recipe_detail(recipe_name):

    # First check if recipe exists in MongoDB database
    recipe = db.recipes.find_one({"name": {"$regex": recipe_name, "$options": "i"}})

    if recipe:
        source = "database"
    else:
        # Check if this exact recipe was already fully generated in the last search
        last_results = session.get("last_search_recipes", [])
        matched = next((r for r in last_results if r.get("name", "").lower() == recipe_name.lower()), None)

        if matched and matched.get("ingredients"):
            # Reuse the exact data from search — zero extra AI calls, guaranteed consistency
            source = "ai"
            recipe = matched
            recipe["estimated_total_cost"] = matched.get("estimated_cost", "₱0")

        else:
            # Fallback: no search context at all (e.g. direct URL visit) — generate fresh
            source = "ai"
            search_budget = session.get("budget", "300")
            search_household = session.get("household_size", "1")

            try:
                prompt = f"""
You are a Filipino recipe assistant. Generate a detailed Filipino recipe for: {recipe_name}

This recipe must be sized for {search_household} person(s) and fit within a total budget of ₱{search_budget}.

STRICT RULES:
1. Use these REAL reference prices per kilo as your baseline — do not invent unrealistic numbers: Chicken ₱180-220, Pork ₱280-320, Beef ₱380-450, Shrimp ₱320-450, Bangus/Milkfish ₱180-220, Tilapia ₱120-150, Rice ₱50-60, common vegetables (eggplant, okra, sitaw, kangkong) ₱40-80 per bundle/kilo, onions/garlic/tomatoes ₱80-150 per kilo, soy sauce/vinegar ₱15-30 per bottle.
2. Scale ALL ingredient quantities and prices specifically for {search_household} serving(s).
3. The "estimated_total_cost" field MUST exactly equal the sum of all ingredient "estimated_price" values, and must not exceed ₱{search_budget}. Calculate this carefully before responding.
4. Category MUST be exactly one of: Pork, Chicken, Beef, Seafood, Vegetable, Soup, Noodles, Snack, Other.
5. Provide 2-4 relevant lowercase tags.

Respond ONLY in this exact JSON format, no extra text:
{{
  "name": "Recipe Name",
  "description": "2-3 sentence description of the dish",
  "servings": "{search_household}",
  "prep_time": "XX mins",
  "cook_time": "XX mins",
  "estimated_total_cost": "₱XXX",
  "category": "One of: Pork, Chicken, Beef, Seafood, Vegetable, Soup, Noodles, Snack, Other",
  "tags": ["tag1", "tag2", "tag3"],
  "ingredients": [
    {{
      "name": "Ingredient Name",
      "quantity": "1 kg",
      "estimated_price": "₱XXX"
    }}
  ],
  "instructions": [
    "Step 1: Do this first.",
    "Step 2: Do this next.",
    "Step 3: Continue cooking.",
    "Step 4: Final step."
  ],
  "tips": "Optional cooking tip here."
}}
"""
                response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7
                )
                response_text = response.choices[0].message.content.strip()

                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()

                recipe = json.loads(response_text)

                if "category" not in recipe or not recipe["category"]:
                    recipe["category"] = "Other"
                if "tags" not in recipe or not recipe["tags"]:
                    recipe["tags"] = []

            except Exception as e:
                print(f"Groq error: {e}")
                flash("Could not load recipe details. Please try again.", "danger")
                return redirect(url_for("recommend"))

    household_size = session.get("household_size", recipe.get("servings", 1))

    try:
        household_size = int(household_size)
        if household_size < 1:
            household_size = 1
    except (ValueError, TypeError):
        household_size = 1

    # Log AI-generated recipes for admin review (skip duplicates)
    if source == "ai":
        from datetime import datetime
        existing_log = db.ai_recipe_logs.find_one({"name": {"$regex": f"^{recipe.get('name', recipe_name)}$", "$options": "i"}})

        if not existing_log:
            db.ai_recipe_logs.insert_one({
                "name": recipe.get("name", recipe_name),
                "description": recipe.get("description", ""),
                "servings": recipe.get("servings", ""),
                "prep_time": recipe.get("prep_time", ""),
                "cook_time": recipe.get("cook_time", ""),
                "estimated_total_cost": recipe.get("estimated_total_cost", ""),
                "ingredients": recipe.get("ingredients", []),
                "instructions": recipe.get("instructions", []),
                "tips": recipe.get("tips", ""),
                "category": recipe.get("category", "Other"),
                "tags": recipe.get("tags", []),
                "viewed_by": current_user.username,
                "date_generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "status": "pending",
                "view_count": 1
            })
        else:
            db.ai_recipe_logs.update_one(
                {"_id": existing_log["_id"]},
                {"$inc": {"view_count": 1}}
            )

    return render_template("recipe_detail.html",
                           recipe=recipe,
                           source=source,
                           recipe_name=recipe_name,
                           household_size=household_size)
# ─────────────────────────────────────────────
# MARK RECIPE AS COOKED
# ─────────────────────────────────────────────

@app.route("/recipe/<recipe_name>/cooked", methods=["POST"])
@login_required
def mark_cooked(recipe_name):
    from datetime import datetime

    user_data = db.users.find_one({"_id": ObjectId(current_user.id)})
    cooking_history = user_data.get("cooking_history", [])

    # Check if this is the first time cooking this recipe
    cooked_names = [h["name"] for h in cooking_history]
    is_first_time = recipe_name not in cooked_names

    # Add to cooking history
    db.users.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$push": {"cooking_history": {
            "name": recipe_name,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        }}}
    )

    log_activity("cooked", current_user.username, recipe_name)

    # Award points
    points_earned = 15 if is_first_time else 10
    new_points = user_data.get("points", 0) + points_earned

    # Update level based on points
    if new_points >= 600:
        new_level = "Master Chef"
    elif new_points >= 300:
        new_level = "Skilled Cook"
    elif new_points >= 100:
        new_level = "Home Cook"
    else:
        new_level = "Beginner Cook"

    # Check and award badges
    new_badges = user_data.get("badges", [])

    # Badge: First Recipe Cooked
    if len(cooking_history) == 0 and "🥄 First Cook" not in new_badges:
        new_badges.append("🥄 First Cook")
        flash("🎉 Badge Unlocked: First Cook!", "success")

    # Badge: Rising Chef (reach 100 points)
    if new_points >= 100 and "⭐ Rising Chef" not in new_badges:
        new_badges.append("⭐ Rising Chef")
        flash("🎉 Badge Unlocked: Rising Chef!", "success")

    # Badge: Adobo Expert (cook 3 adobo recipes)
    adobo_count = sum(1 for h in cooking_history if "adobo" in h["name"].lower())
    if adobo_count >= 2 and "🍗 Adobo Expert" not in new_badges:
        new_badges.append("🍗 Adobo Expert")
        flash("🎉 Badge Unlocked: Adobo Expert!", "success")

    # Badge: Budget Master (cook 5 recipes total)
    if len(cooking_history) >= 4 and "💰 Budget Master" not in new_badges:
        new_badges.append("💰 Budget Master")
        flash("🎉 Badge Unlocked: Budget Master!", "success")

    # Save updated points, level, badges
    db.users.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {
            "points": new_points,
            "level": new_level,
            "badges": new_badges
        }}
    )

    flash(f"✅ Great job! You earned {points_earned} points!", "success")
    return redirect(url_for("recipe_detail", recipe_name=recipe_name))

# ─────────────────────────────────────────────
# TOGGLE FAVORITE
# ─────────────────────────────────────────────

@app.route("/recipe/<recipe_name>/favorite", methods=["POST"])
@login_required
def toggle_favorite(recipe_name):
    user_data = db.users.find_one({"_id": ObjectId(current_user.id)})
    favorites = user_data.get("favorites", [])

    if recipe_name in favorites:
        # Remove from favorites
        db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$pull": {"favorites": recipe_name}}
        )
        flash("Recipe removed from favorites.", "success")
    else:
        # Add to favorites
        db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$push": {"favorites": recipe_name}}
        )
        flash("Recipe saved to favorites!", "success")

    return redirect(url_for("recipe_detail", recipe_name=recipe_name))


# ─────────────────────────────────────────────
# FAVORITES PAGE
# ─────────────────────────────────────────────

@app.route("/favorites")
@login_required
def favorites():
    user_data = db.users.find_one({"_id": ObjectId(current_user.id)})
    favorite_recipes = user_data.get("favorites", [])
    return render_template("favorites.html", favorites=favorite_recipes)


# ─────────────────────────────────────────────
# COOKING HISTORY PAGE
# ─────────────────────────────────────────────

@app.route("/cooking-history")
@login_required
def cooking_history():
    user_data = db.users.find_one({"_id": ObjectId(current_user.id)})
    history = user_data.get("cooking_history", [])

    # Count frequency of each recipe
    frequency = {}
    for item in history:
        name = item["name"]
        frequency[name] = frequency.get(name, 0) + 1

    # Sort history by most recent first
    history_sorted = sorted(history, key=lambda x: x["date"], reverse=True)

    # Most cooked recipes
    most_cooked = sorted(frequency.items(), key=lambda x: x[1], reverse=True)[:5]

    return render_template("cooking_history.html",
                           history=history_sorted,
                           most_cooked=most_cooked)

from functools import wraps

# ─────────────────────────────────────────────
# ADMIN DECORATOR
# ─────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_data = db.users.find_one({"_id": ObjectId(current_user.id)})
        if not user_data.get("is_admin", False):
            flash("Access denied. Admins only.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated_function

# ─────────────────────────────────────────────
# ADMIN DASHBOARD
# ─────────────────────────────────────────────

@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    total_users = db.users.count_documents({})
    total_recipes = db.recipes.count_documents({})
    recent_users = list(db.users.find().sort("_id", -1).limit(5))

    return render_template("admin/dashboard.html",
                           total_users=total_users,
                           total_recipes=total_recipes,
                           recent_users=recent_users)

# ─────────────────────────────────────────────
# ADMIN - MANAGE USERS
# ─────────────────────────────────────────────

@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    users = list(db.users.find())
    return render_template("admin/users.html", users=users)


@app.route("/admin/users/delete/<user_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    db.users.delete_one({"_id": ObjectId(user_id)})
    flash("User deleted successfully.", "success")
    return redirect(url_for("admin_users"))


# ─────────────────────────────────────────────
# ADMIN - MANAGE RECIPES
# ─────────────────────────────────────────────

@app.route("/admin/recipes")
@login_required
@admin_required
def admin_recipes():
    category_filter = request.args.get("category", "")

    if category_filter:
        recipes = list(db.recipes.find({"category": category_filter}))
    else:
        recipes = list(db.recipes.find())

    categories = db.recipes.distinct("category")

    return render_template("admin/recipes.html",
                           recipes=recipes,
                           categories=categories,
                           selected_category=category_filter)

@app.route("/admin/recipes/add", methods=["GET", "POST"])
@login_required
@admin_required
def admin_add_recipe():
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        servings = request.form.get("servings")
        prep_time = request.form.get("prep_time")
        cook_time = request.form.get("cook_time")
        estimated_total_cost = request.form.get("estimated_total_cost")
        tips = request.form.get("tips")
        category = request.form.get("category")
        tags_raw = request.form.get("tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        # Process ingredients
        ingredient_names = request.form.getlist("ingredient_name")
        ingredient_quantities = request.form.getlist("ingredient_quantity")
        ingredient_prices = request.form.getlist("ingredient_price")

        ingredients = []
        for i in range(len(ingredient_names)):
            if ingredient_names[i]:
                ingredients.append({
                    "name": ingredient_names[i],
                    "quantity": ingredient_quantities[i],
                    "estimated_price": ingredient_prices[i]
                })

        # Process instructions
        instructions_raw = request.form.get("instructions", "")
        instructions = [line.strip() for line in instructions_raw.split("\n") if line.strip()]

        db.recipes.insert_one({
            "name": name,
            "description": description,
            "servings": servings,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "estimated_total_cost": estimated_total_cost,
            "ingredients": ingredients,
            "instructions": instructions,
            "tips": tips,
            "category": category,
            "tags": tags
        })

        flash("Recipe added successfully!", "success")
        return redirect(url_for("admin_recipes"))

    return render_template("admin/add_recipe.html")


@app.route("/admin/recipes/edit/<recipe_id>", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_recipe(recipe_id):
    recipe = db.recipes.find_one({"_id": ObjectId(recipe_id)})

    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        servings = request.form.get("servings")
        prep_time = request.form.get("prep_time")
        cook_time = request.form.get("cook_time")
        estimated_total_cost = request.form.get("estimated_total_cost")
        tips = request.form.get("tips")
        category = request.form.get("category")
        tags_raw = request.form.get("tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        ingredient_names = request.form.getlist("ingredient_name")
        ingredient_quantities = request.form.getlist("ingredient_quantity")
        ingredient_prices = request.form.getlist("ingredient_price")

        ingredients = []
        for i in range(len(ingredient_names)):
            if ingredient_names[i]:
                ingredients.append({
                    "name": ingredient_names[i],
                    "quantity": ingredient_quantities[i],
                    "estimated_price": ingredient_prices[i]
                })

        instructions_raw = request.form.get("instructions", "")
        instructions = [line.strip() for line in instructions_raw.split("\n") if line.strip()]

        db.recipes.update_one(
            {"_id": ObjectId(recipe_id)},
            {"$set": {
                "name": name,
                "description": description,
                "servings": servings,
                "prep_time": prep_time,
                "cook_time": cook_time,
                "estimated_total_cost": estimated_total_cost,
                "ingredients": ingredients,
                "instructions": instructions,
                "tips": tips,
                "category": category,
                "tags": tags
            }}
        )

        flash("Recipe updated successfully!", "success")
        return redirect(url_for("admin_recipes"))

    return render_template("admin/edit_recipe.html", recipe=recipe)


@app.route("/admin/recipes/delete/<recipe_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_recipe(recipe_id):
    db.recipes.delete_one({"_id": ObjectId(recipe_id)})
    flash("Recipe deleted successfully.", "success")
    return redirect(url_for("admin_recipes"))

# ─────────────────────────────────────────────
# FORGOT PASSWORD
# ─────────────────────────────────────────────

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        user_data = db.users.find_one({"email": email})

        if user_data:
            # In a real app, you'd email a reset link with a token.
            # For this school project, we'll let them reset directly
            # by confirming their email.
            session["reset_email"] = email
            flash("Email verified! Please set your new password.", "success")
            return redirect(url_for("reset_password"))
        else:
            flash("No account found with that email.", "danger")

    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = session.get("reset_email")

    if not email:
        flash("Please verify your email first.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("reset_password"))

        hashed_pw = bcrypt.generate_password_hash(new_password).decode("utf-8")

        db.users.update_one(
            {"email": email},
            {"$set": {"password": hashed_pw}}
        )

        session.pop("reset_email", None)
        flash("Password reset successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html")

# ─────────────────────────────────────────────
# ADMIN - EDIT USER
# ─────────────────────────────────────────────

@app.route("/admin/users/edit/<user_id>", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_user(user_id):
    user = db.users.find_one({"_id": ObjectId(user_id)})

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("admin_users"))

    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        points = request.form.get("points")
        level = request.form.get("level")
        is_admin = True if request.form.get("is_admin") == "on" else False

       # Validate points is a number
        try:
            points = int(points)
        except (ValueError, TypeError):
            points = user.get("points", 0)

        # Auto-calculate level based on points (ignores whatever the dropdown said)
        if points >= 600:
            level = "Master Chef"
        elif points >= 300:
            level = "Skilled Cook"
        elif points >= 100:
            level = "Home Cook"
        else:
            level = "Beginner Cook"

        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "username": username,
                "email": email,
                "points": points,
                "level": level,
                "is_admin": is_admin
            }}
        )

        flash("User updated successfully!", "success")
        return redirect(url_for("admin_users"))

    return render_template("admin/edit_user.html", user=user)

# ─────────────────────────────────────────────
# ADMIN - UPDATE INGREDIENT PRICES
# ─────────────────────────────────────────────

@app.route("/admin/recipes/<recipe_id>/prices", methods=["GET", "POST"])
@login_required
@admin_required
def admin_update_prices(recipe_id):
    recipe = db.recipes.find_one({"_id": ObjectId(recipe_id)})

    if not recipe:
        flash("Recipe not found.", "danger")
        return redirect(url_for("admin_recipes"))

    if request.method == "POST":
        ingredient_prices = request.form.getlist("ingredient_price")
        ingredients = recipe.get("ingredients", [])

        # Update each ingredient's price by matching index order
        updated_ingredients = []
        total_cost = 0

        for i, ingredient in enumerate(ingredients):
            new_price = ingredient_prices[i] if i < len(ingredient_prices) else ingredient.get("estimated_price", "₱0")

            updated_ingredients.append({
                "name": ingredient.get("name"),
                "quantity": ingredient.get("quantity"),
                "estimated_price": new_price
            })

            # Add up the numeric value for the new total cost
            digits = "".join(c for c in new_price if c.isdigit())
            total_cost += int(digits) if digits else 0

        db.recipes.update_one(
            {"_id": ObjectId(recipe_id)},
            {"$set": {
                "ingredients": updated_ingredients,
                "estimated_total_cost": f"₱{total_cost}"
            }}
        )

        flash("Ingredient prices updated successfully!", "success")
        return redirect(url_for("admin_recipes"))

    return render_template("admin/update_prices.html", recipe=recipe)

# ─────────────────────────────────────────────
# ADMIN - REVIEW AI-GENERATED RECIPES
# ─────────────────────────────────────────────

@app.route("/admin/ai-review")
@login_required
@admin_required
def admin_ai_review():
    status_filter = request.args.get("status", "pending")

    if status_filter == "all":
        logs = list(db.ai_recipe_logs.find().sort("view_count", -1))
    else:
        logs = list(db.ai_recipe_logs.find({"status": status_filter}).sort("view_count", -1))

    pending_count = db.ai_recipe_logs.count_documents({"status": "pending"})

    return render_template("admin/ai_review.html",
                           logs=logs,
                           status_filter=status_filter,
                           pending_count=pending_count)
# ─────────────────────────────────────────────
# ADMIN - EDIT AI-GENERATED RECIPE BEFORE APPROVAL
# ─────────────────────────────────────────────

@app.route("/admin/ai-review/<log_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_ai_recipe(log_id):
    log = db.ai_recipe_logs.find_one({"_id": ObjectId(log_id)})

    if not log:
        flash("Log not found.", "danger")
        return redirect(url_for("admin_ai_review"))

    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        servings = request.form.get("servings")
        prep_time = request.form.get("prep_time")
        cook_time = request.form.get("cook_time")
        estimated_total_cost = request.form.get("estimated_total_cost")
        tips = request.form.get("tips")
        category = request.form.get("category")
        tags_raw = request.form.get("tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        ingredient_names = request.form.getlist("ingredient_name")
        ingredient_quantities = request.form.getlist("ingredient_quantity")
        ingredient_prices = request.form.getlist("ingredient_price")

        ingredients = []
        for i in range(len(ingredient_names)):
            if ingredient_names[i]:
                ingredients.append({
                    "name": ingredient_names[i],
                    "quantity": ingredient_quantities[i],
                    "estimated_price": ingredient_prices[i]
                })

        instructions_raw = request.form.get("instructions", "")
        instructions = [line.strip() for line in instructions_raw.split("\n") if line.strip()]

        db.ai_recipe_logs.update_one(
            {"_id": ObjectId(log_id)},
            {"$set": {
                "name": name,
                "description": description,
                "servings": servings,
                "prep_time": prep_time,
                "cook_time": cook_time,
                "estimated_total_cost": estimated_total_cost,
                "ingredients": ingredients,
                "instructions": instructions,
                "tips": tips,
                "category": category,
                "tags": tags
            }}
        )

        flash("AI recipe updated! Review the changes and approve when ready.", "success")
        return redirect(url_for("admin_ai_review"))

    return render_template("admin/edit_ai_recipe.html", log=log)

@app.route("/admin/ai-review/<log_id>/approve", methods=["POST"])
@login_required
@admin_required
def admin_approve_ai_recipe(log_id):
    log = db.ai_recipe_logs.find_one({"_id": ObjectId(log_id)})

    if not log:
        flash("Log not found.", "danger")
        return redirect(url_for("admin_ai_review"))

    # Save into the permanent recipes collection
    db.recipes.insert_one({
        "name": log.get("name"),
        "description": log.get("description"),
        "servings": log.get("servings"),
        "prep_time": log.get("prep_time"),
        "cook_time": log.get("cook_time"),
        "estimated_total_cost": log.get("estimated_total_cost"),
        "ingredients": log.get("ingredients", []),
        "instructions": log.get("instructions", []),
        "tips": log.get("tips", ""),
        "category": log.get("category", "Other"),
        "tags": log.get("tags", [])
    })

    db.ai_recipe_logs.update_one(
        {"_id": ObjectId(log_id)},
        {"$set": {"status": "approved"}}
    )

    flash(f"'{log.get('name')}' approved and added to the recipe database!", "success")
    return redirect(url_for("admin_ai_review"))


@app.route("/admin/ai-review/<log_id>/dismiss", methods=["POST"])
@login_required
@admin_required
def admin_dismiss_ai_recipe(log_id):
    db.ai_recipe_logs.update_one(
        {"_id": ObjectId(log_id)},
        {"$set": {"status": "dismissed"}}
    )
    flash("Recipe dismissed.", "success")
    return redirect(url_for("admin_ai_review"))

# ─────────────────────────────────────────────
# ADMIN - USER ACTIVITY STATISTICS
# ─────────────────────────────────────────────

@app.route("/admin/statistics")
@login_required
@admin_required
def admin_statistics():
    from datetime import timedelta

    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # Active users today
    active_today = len(db.activity_logs.distinct("username", {"date": today}))

    # Active users this week
    active_week = len(db.activity_logs.distinct("username", {"date": {"$gte": week_ago}}))

    # Total searches this week
    searches_week = db.activity_logs.count_documents({"action_type": "search", "date": {"$gte": week_ago}})

    # Total recipes cooked this week
    cooked_week = db.activity_logs.count_documents({"action_type": "cooked", "date": {"$gte": week_ago}})

    # New registrations this week
    new_users_week = db.activity_logs.count_documents({"action_type": "register", "date": {"$gte": week_ago}})

    # Most searched dishes (all time)
    search_pipeline = [
        {"$match": {"action_type": "search"}},
        {"$group": {"_id": "$details", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    most_searched = list(db.activity_logs.aggregate(search_pipeline))

    # Most cooked recipes platform-wide (all time)
    cooked_pipeline = [
        {"$match": {"action_type": "cooked"}},
        {"$group": {"_id": "$details", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    most_cooked_platform = list(db.activity_logs.aggregate(cooked_pipeline))

    # Recent activity feed (last 20 events)
    recent_activity = list(db.activity_logs.find().sort("timestamp", -1).limit(20))

    return render_template("admin/statistics.html",
                           active_today=active_today,
                           active_week=active_week,
                           searches_week=searches_week,
                           cooked_week=cooked_week,
                           new_users_week=new_users_week,
                           most_searched=most_searched,
                           most_cooked_platform=most_cooked_platform,
                           recent_activity=recent_activity)

# ─────────────────────────────────────────────
# WEEKLY CHALLENGES PAGE
# ─────────────────────────────────────────────

@app.route("/challenges")
@login_required
def challenges():
    weekly_challenges = get_weekly_challenges()
    progress_data = get_user_challenge_progress(current_user.id, weekly_challenges)

    return render_template("challenges.html", challenges=progress_data)


@app.route("/challenges/claim/<claim_key>", methods=["POST"])
@login_required
def claim_challenge(claim_key):
    weekly_challenges = get_weekly_challenges()
    progress_data = get_user_challenge_progress(current_user.id, weekly_challenges)

    matched_challenge = next((c for c in progress_data if c["claim_key"] == claim_key), None)

    if not matched_challenge:
        flash("Challenge not found.", "danger")
        return redirect(url_for("challenges"))

    if matched_challenge["claimed"]:
        flash("You already claimed this reward!", "danger")
        return redirect(url_for("challenges"))

    if not matched_challenge["completed"]:
        flash("Challenge not completed yet!", "danger")
        return redirect(url_for("challenges"))

    # Award points and mark as claimed
    user_data = db.users.find_one({"_id": ObjectId(current_user.id)})
    new_points = user_data.get("points", 0) + matched_challenge["points"]

    # Recalculate level
    if new_points >= 600:
        new_level = "Master Chef"
    elif new_points >= 300:
        new_level = "Skilled Cook"
    elif new_points >= 100:
        new_level = "Home Cook"
    else:
        new_level = "Beginner Cook"

    db.users.update_one(
        {"_id": ObjectId(current_user.id)},
        {
            "$set": {"points": new_points, "level": new_level},
            "$push": {"claimed_challenges": claim_key}
        }
    )

    flash(f"🎉 Challenge complete! You earned {matched_challenge['points']} bonus points!", "success")
    return redirect(url_for("challenges"))