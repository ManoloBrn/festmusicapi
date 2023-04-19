import os
from flask import Flask, request, jsonify
from google.cloud import firestore
import datetime

# Initialize Firestore
db = firestore.Client()

app = Flask(__name__)

@app.route('/festivals', methods=['GET'])
def get_festival_data():
    festival_id = request.args.get('festivalId')
    if festival_id is None:
        return jsonify({"error": "Missing festivalId parameter"}), 400

    doc_ref = db.collection("festivals").document(festival_id)
    doc = doc_ref.get()

    if not doc.exists:
        return jsonify({"error": "Festival not found"}), 404

    festival_data = doc.to_dict()

    # Convert datetime objects to ISO8601 strings
    for presentation in festival_data["presentations"]:
        for band in presentation["bands"]:
            band["start_time"] = band["start_time"].isoformat()
            band["end_time"] = band["end_time"].isoformat()

    return jsonify(festival_data)

@app.route('/users', methods=['POST'])
def create_user():
    username = request.json.get('username')

    if not username:
        return jsonify({"error": "Missing username parameter"}), 400

    users_collection = db.collection("users")
    user_query = users_collection.where("username", "==", username).stream()

    existing_user = None
    for user in user_query:
        existing_user = user

    if existing_user:
        return jsonify({"message": "User already exists", "user": existing_user.to_dict(), "user_id": existing_user.id}), 201

    new_user = {"username": username, "following": []}
    created_user_ref = users_collection.document()  # Create a new document reference with a random ID
    created_user_ref.set(new_user)  # Set the new user data

    return jsonify({"message": "User created successfully", "user": new_user, "user_id": created_user_ref.id}), 201


@app.route('/users/find', methods=['GET'])
def find_users():
    query_string = request.args.get('user')

    if query_string is None:
        return jsonify({"error": "Missing 'user' parameter"}), 400

    users_collection = db.collection("users")
    users_query = users_collection.where("username", ">=", query_string)\
                                   .where("username", "<", query_string + u"\uf8ff").stream()

    found_users = []
    for user in users_query:
        found_users.append({"username": user.to_dict()["username"], "user_id": user.id})

    return jsonify(found_users)

@app.route('/users/<user_id>/follow', methods=['POST'])
def follow_user(user_id):
    data = request.json

    if not data:
        return jsonify({"error": "Missing request body"}), 400

    user_to_follow_id = data.get('user_id')
    user_to_follow_username = data.get('username')

    if not user_to_follow_id or not user_to_follow_username:
        return jsonify({"error": "Missing 'user_id' or 'username' in the request body"}), 400

    user_ref = db.collection("users").document(user_id)
    user = user_ref.get()

    if not user.exists:
        return jsonify({"error": "User not found"}), 404

    user_to_follow_ref = db.collection("users").document(user_to_follow_id)
    user_to_follow = user_to_follow_ref.get()

    if not user_to_follow.exists:
        return jsonify({"error": "User to follow not found"}), 404

    user_ref.update({
        "following": firestore.ArrayUnion([{
            "user_id": user_to_follow_id,
            "username": user_to_follow_username
        }])
    })

    return jsonify({"message": "User followed successfully"})

@app.route('/users/<user_id>/<festival_id>/favorite', methods=['POST'])
def favorite_band(user_id, festival_id):
    data = request.json

    if not data:
        return jsonify({"error": "Missing request body"}), 400

    presentation_day = data.get('presentation_day')
    band_id = data.get('band_id')
    favorite = data.get('favorite')

    if not presentation_day or not band_id or favorite is None:
        return jsonify({"error": "Missing required fields in the request body"}), 400

    user_ref = db.collection("users").document(user_id)

    if not user_ref.get().exists:
        return jsonify({"error": "User not found"}), 404

    festival_ref = user_ref.collection("festivals").document(festival_id)
    festival = festival_ref.get()

    if not festival.exists:
        festival_ref.set({"favorite_bands": []})
        favorite_bands = []
    else:
        favorite_bands = festival.to_dict().get("favorite_bands", [])

    band_entry = {"presentation_day": presentation_day, "band_id": band_id}

    if favorite:
        if band_entry not in favorite_bands:
            favorite_bands.append(band_entry)
    else:
        if band_entry in favorite_bands:
            favorite_bands.remove(band_entry)

    festival_ref.update({"favorite_bands": favorite_bands})

    return jsonify({"message": "Band favorite status updated successfully"})

@app.route('/users/<user_id>/<festival_id>/schedule', methods=['GET'])
def get_user_schedule(user_id, festival_id):
    user_ref = db.collection("users").document(user_id)
    user = user_ref.get()

    if not user.exists:
        return jsonify({"error": "User not found"}), 404

    festival_ref = db.collection("festivals").document(festival_id)
    festival = festival_ref.get()

    if not festival.exists:
        return jsonify({"error": "Festival not found"}), 404

    user_festival_ref = user_ref.collection("festivals").document(festival_id)
    user_festival = user_festival_ref.get()

    favorite_bands = user_festival.to_dict().get("favorite_bands", []) if user_festival.exists else []
    festival_details = festival.to_dict()
    schedule = {
        "festival_id": festival_id,
        "festival_name": festival_details.get("festival_name", ""),
        "festival_dates": festival_details.get("dates", []),
        "presentations": []
    }

    user_following = user.to_dict().get("following", [])

    followed_users_festival_data = {}
    for followed_user in user_following:
        followed_user_id = followed_user["user_id"]
        followed_user_festival_ref = db.collection("users").document(followed_user_id).collection("festivals").document(festival_id)
        followed_user_festival = followed_user_festival_ref.get()

        if followed_user_festival.exists:
            followed_users_festival_data[followed_user_id] = followed_user_festival.to_dict()

    for presentation in festival_details["presentations"]:
        user_presentation = {
            "presentation_day": presentation["presentation_day"],
            "bands": []
        }

        for band in presentation["bands"]:
            band_id = band["band_id"]

            band_data = {
                "band_id": band_id,
                "band_name": band["band_name"],
                "start_time": band["start_time"].isoformat(),
                "end_time": band["end_time"].isoformat(),
                "stage": band["scenario"],
                "favorite": {"presentation_day": presentation["presentation_day"], "band_id": band_id} in favorite_bands,
                "following": []
            }

            for user_id, followed_user_festival in followed_users_festival_data.items():
                followed_user_favorite_bands = followed_user_festival.get("favorite_bands", [])

                if {"presentation_day": presentation["presentation_day"], "band_id": band_id} in followed_user_favorite_bands:
                    followed_user = next((u for u in user_following if u["user_id"] == user_id), None)
                    if followed_user:
                        band_data["following"].append({
                            "user_id": user_id,
                            "username": followed_user["username"]
                        })

            user_presentation["bands"].append(band_data)

        schedule["presentations"].append(user_presentation)

    return jsonify(schedule)

    user_ref = db.collection("users").document(user_id)
    user = user_ref.get()

    if not user.exists:
        return jsonify({"error": "User not found"}), 404

    festival_ref = db.collection("festivals").document(festival_id)
    festival = festival_ref.get()

    if not festival.exists:
        return jsonify({"error": "Festival not found"}), 404

    user_festival_ref = user_ref.collection("festivals").document(festival_id)
    user_festival = user_festival_ref.get()

    favorite_bands = user_festival.to_dict().get("favorite_bands", []) if user_festival.exists else []
    festival_details = festival.to_dict()
    schedule = {
        "festival_id": festival_id,
        "festival_name": festival_details.get("festival_name", ""),
        "festival_dates": festival_details.get("dates", []),
        "presentations": []
    }

    user_following = user.to_dict().get("following", [])
    followed_users_ids = [u["user_id"] for u in user_following]

    followed_users_festivals = db.collection_group("festivals").where("festival_id", "==", festival_id).stream()
    followed_users_festival_data = {doc.reference.parent.parent.id: doc.to_dict() for doc in followed_users_festivals if doc.reference.parent.parent.id in followed_users_ids}

    for presentation in festival_details["presentations"]:
        user_presentation = {
            "presentation_day": presentation["presentation_day"],
            "bands": []
        }

        for band in presentation["bands"]:
            band_id = band["band_id"]

            band_data = {
                "band_id": band_id,
                "band_name": band["band_name"],
                "start_time": band["start_time"].isoformat(),
                "end_time": band["end_time"].isoformat(),
                "stage": band["scenario"],
                "favorite": {"presentation_day": presentation["presentation_day"], "band_id": band_id} in favorite_bands,
                "following": []
            }

            for user_id, followed_user_festival in followed_users_festival_data.items():
                followed_user_favorite_bands = followed_user_festival.get("favorite_bands", [])

                if {"presentation_day": presentation["presentation_day"], "band_id": band_id} in followed_user_favorite_bands:
                    followed_user = next((u for u in user_following if u["user_id"] == user_id), None)
                    if followed_user:
                        band_data["following"].append({
                            "user_id": user_id,
                            "username": followed_user["username"]
                        })

            user_presentation["bands"].append(band_data)

        schedule["presentations"].append(user_presentation)

    return jsonify(schedule)

    user_ref = db.collection("users").document(user_id)
    user = user_ref.get()

    if not user.exists:
        return jsonify({"error": "User not found"}), 404

    festival_ref = db.collection("festivals").document(festival_id)
    festival = festival_ref.get()

    if not festival.exists:
        return jsonify({"error": "Festival not found"}), 404

    user_festival_ref = user_ref.collection("festivals").document(festival_id)
    user_festival = user_festival_ref.get()

    favorite_bands = user_festival.to_dict().get("favorite_bands", []) if user_festival.exists else []
    festival_details = festival.to_dict()
    schedule = {
        "festival_id": festival_id,
        "festival_name": festival_details.get("festival_name", ""),
        "festival_dates": festival_details.get("dates", []),
        "presentations": []
    }

    user_following = user.to_dict().get("following", [])
    followed_users_usernames = [u["username"] for u in user_following]

    followed_users_festivals = db.collection_group("festivals").where("festival_id", "==", festival_id).stream()
    followed_users_festival_data = {doc.reference.parent.parent.id: doc.to_dict() for doc in followed_users_festivals if doc.reference.parent.parent.get().to_dict()["username"] in followed_users_usernames}

    for presentation in festival_details["presentations"]:
        user_presentation = {
            "presentation_day": presentation["presentation_day"],
            "bands": []
        }

        for band in presentation["bands"]:
            band_id = band["band_id"]

            band_data = {
                "band_id": band_id,
                "band_name": band["band_name"],
                "start_time": band["start_time"].isoformat(),
                "end_time": band["end_time"].isoformat(),
                "stage": band["scenario"],
                "favorite": {"presentation_day": presentation["presentation_day"], "band_id": band_id} in favorite_bands,
                "following": []
            }

            for user_id, followed_user_festival in followed_users_festival_data.items():
                followed_user_favorite_bands = followed_user_festival.get("favorite_bands", [])

                if {"presentation_day": presentation["presentation_day"], "band_id": band_id} in followed_user_favorite_bands:
                    followed_user = db.collection("users").document(user_id).get().to_dict()
                    band_data["following"].append({
                        "user_id": user_id,
                        "username": followed_user["username"]
                    })

            user_presentation["bands"].append(band_data)

        schedule["presentations"].append(user_presentation)

    return jsonify(schedule)

@app.route('/users/<user_id>/following', methods=['GET'])
def get_user_following(user_id):
    # Get the 'following' data from Firestore
    user_ref = db.collection('users').document(user_id)
    user_data = user_ref.get().to_dict()

    if user_data and 'following' in user_data:
        following_data = user_data['following']
        return jsonify(following_data), 200
    else:
        return jsonify({'error': 'User not found or has no following data'}), 404

@app.route('/users/<user_id>/following/<following_id>', methods=['DELETE'])
def unfollow_user(user_id, following_id):
    user_ref = db.collection('users').document(user_id)
    user_data = user_ref.get().to_dict()

    if user_data and 'following' in user_data:
        # Remove the user from the following list
        updated_following = [follow for follow in user_data['following'] if follow['user_id'] != following_id]

        if len(updated_following) != len(user_data['following']):
            # Update the 'following' field in Firestore
            user_ref.update({'following': updated_following})
            return jsonify({'status': 'success', 'message': f'Unfollowed user {following_id}'}), 200
        else:
            return jsonify({'error': f'User {following_id} not found in following list'}), 404
    else:
        return jsonify({'error': 'User not found or has no following data'}), 404

# Run the functions-framework for local development
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


