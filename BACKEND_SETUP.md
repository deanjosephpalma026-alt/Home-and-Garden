# Home & Garden Flask Backend - Setup Guide

## Overview
This Flask backend provides REST APIs for the Home & Garden e-commerce mobile app. It can run on a local network or be deployed to the cloud for internet access.

## Requirements
- Python 3.8+
- PostgreSQL (for database)
- Internet connection (for Supabase credentials)

## Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Database Setup

#### Option A: Using Supabase (Cloud PostgreSQL - Recommended)
Supabase is already configured in the code. The database is hosted in the cloud.

#### Option B: Local PostgreSQL
If you prefer a local database:
1. Install PostgreSQL
2. Create a database:
   ```bash
   psql -U postgres
   CREATE DATABASE home_and_garden_db;
   ```
3. Update `config.py` with your database credentials

### 3. Environment Configuration
Create a `.env` file in the root directory:
```env
FLASK_ENV=development
DATABASE_URL=postgresql://user:password@localhost/home_and_garden_db
SUPABASE_URL=https://your-supabase-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SECRET_KEY=your-secret-key-for-flask
```

Or use Supabase defaults (already configured in code):
- Supabase URL: `https://dwbjfdyvtfqrhyjikazq.supabase.co`
- Database is hosted in the cloud

## Running the Server

### Local Network (Development)
```bash
# Find your PC's IP address
ipconfig    # Windows
ifconfig    # macOS/Linux

# Note the IPv4 Address (e.g., 192.168.1.4)

# Start Flask server
python app.py

# Server will run on:
# http://0.0.0.0:5000 (all interfaces)
# Access from mobile:
# http://192.168.1.4:5000
```

### Without Internet Connection
1. Flask backend requires database connection
2. If using Supabase (cloud), internet is needed
3. For offline-only mode, use local PostgreSQL:
   ```bash
   # Configure DATABASE_URL in config.py for local PostgreSQL
   python app.py
   ```

### Production (Cloud Deployment)
Deploy to services like:
- **Heroku** (easiest)
- **AWS EC2**
- **Google Cloud Platform**
- **Azure App Service**

Example Heroku deployment:
```bash
heroku create your-app-name
heroku config:set FLASK_ENV=production
git push heroku main
```

## Key API Endpoints

### Authentication
- `POST /api/mobile/auth/login` - Login with email/password
- `POST /api/mobile/auth/signup` - Create new user account
- `POST /api/mobile/auth/logout` - Logout user

### Products
- `GET /api/mobile/home` - Get featured products
- `GET /api/mobile/products` - Get all products with search/filter
- `GET /api/mobile/products/{id}` - Get product details
- `GET /api/mobile/products/{id}/reviews` - Get product reviews

### Cart
- `GET /api/mobile/cart` - Get user's cart
- `POST /api/mobile/cart` - Add item to cart
- `PUT /api/mobile/cart/{id}` - Update cart item quantity
- `DELETE /api/mobile/cart/{id}` - Remove item from cart

### Orders
- `GET /api/mobile/orders` - Get user's order history
- `POST /api/mobile/checkout` - Create new order

### Profile
- `GET /api/mobile/profile` - Get user profile
- `PUT /api/mobile/profile` - Update user profile

### Locations
- `GET /api/mobile/locations` - Get provinces, cities, barangays

## Configuration Files

### `app.py`
Main Flask application file. Defines routes and initializes the app.

### `config.py`
Configuration settings:
- Database connection
- Supabase credentials
- Flask secret key
- Debug mode

### `database.py`
Database connection and helper functions.

### Routes Directory (`routes/`)
Modular route definitions:
- `main.py` - Main routes
- `api.py` - API routes (products, cart, orders)
- `auth.py` - Authentication routes
- `user.py` - User profile routes
- `mobile_api.py` - Mobile app specific routes
- `admin.py` - Admin routes
- `seller.py` - Seller routes
- `rider.py` - Rider/delivery routes

## Network Accessibility

### Same WiFi Network
1. Start Flask on PC
2. Get your IP address: `ipconfig`
3. Mobile device configures app with: `http://192.168.1.x:5000`
4. Both must be on same WiFi network
5. Check firewall allows port 5000

### Internet (Any Network)
1. Deploy Flask to cloud service (Heroku, AWS, etc.)
2. Get public URL (e.g., `https://my-api.herokuapp.com`)
3. Mobile device configures app with public URL
4. Works from anywhere with internet

## Troubleshooting

### "Connection Refused"
- Flask not running
- Mobile device not on same WiFi
- Firewall blocking port 5000
- Wrong IP address

**Solution:**
```bash
# Start Flask
python app.py

# Verify IP address
ipconfig | findstr IPv4

# Test connection from another device
# Navigate to: http://your-ip:5000/api/health (if endpoint exists)
```

### "Timeout"
- Network latency
- Flask server slow/overloaded
- Check database connection

**Solution:**
- Check Flask logs
- Verify database is running
- Reduce database query complexity

### Database Connection Error
- PostgreSQL not running (if local)
- Wrong credentials in config.py
- Database doesn't exist

**Solution:**
- Start PostgreSQL service
- Update DATABASE_URL in config.py
- Create database: `createdb home_and_garden_db`

### CORS Errors
- Mobile app requests are being blocked
- Already configured with Flask-Cors

**Solution:**
- Verify Flask-CORS is installed
- Check CORS headers in `app.py`

## Environment Variables

Essential variables (set in `.env` or as environment variables):
```env
FLASK_ENV=development          # development or production
DATABASE_URL=...               # PostgreSQL connection string
SUPABASE_URL=...               # Supabase project URL
SUPABASE_KEY=...               # Supabase anon key
SECRET_KEY=...                 # Flask session secret
```

## Development Tips

### Enable Debug Mode
```python
# In app.py
app.run(debug=True)
```

### Test Endpoints
Use Postman or curl:
```bash
# Get all products
curl http://localhost:5000/api/mobile/products

# Login
curl -X POST http://localhost:5000/api/mobile/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password"}'
```

### View Logs
Flask logs requests and errors to console:
```
 * Running on http://0.0.0.0:5000
 * Press CTRL+C to quit
127.0.0.1 - - [01/Jan/2024 12:34:56] "GET /api/health HTTP/1.1" 200 -
```

## Mobile App Integration

### Configuring Backend URL
Users configure the backend URL in the Flutter app Settings:
1. Open Settings
2. Enter backend URL: `http://192.168.1.4:5000`
3. Save settings
4. Restart app

### Offline Support
- App caches products, cart, orders when online
- Uses cached data when backend unavailable
- Supabase authentication always works (cloud-based)

## Security Notes

⚠️ **Development Only**
- Don't use hardcoded credentials
- Don't expose Supabase keys
- Use environment variables for sensitive data

✅ **Production Checklist**
- [ ] Set `FLASK_ENV=production`
- [ ] Use strong SECRET_KEY
- [ ] Enable HTTPS (SSL/TLS)
- [ ] Restrict CORS origins
- [ ] Validate all user inputs
- [ ] Use secure database passwords
- [ ] Keep dependencies updated
- [ ] Regular security audits

## Next Steps

1. **Setup Local Database** (if not using Supabase)
   - Install PostgreSQL
   - Create database
   - Run migrations

2. **Test Endpoints**
   - Use Postman to test APIs
   - Verify all routes work

3. **Deploy to Cloud** (if needed)
   - Choose hosting provider
   - Configure environment variables
   - Deploy application

4. **Connect Mobile App**
   - Configure backend URL in Flutter app
   - Test with both local and cloud backends

## Support

For issues:
1. Check Flask logs for errors
2. Verify database is running
3. Ensure network connectivity
4. Check Supabase credentials
5. Review configuration files

## References
- Flask Documentation: https://flask.palletsprojects.com/
- Supabase Documentation: https://supabase.com/docs
- PostgreSQL Documentation: https://www.postgresql.org/docs/
