import stripe
stripe.Subscription.create(customer=cid, items=[{'price': price_id}])
