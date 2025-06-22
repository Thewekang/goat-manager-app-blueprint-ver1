# Goat Manager Application

A comprehensive web-based goat farm management system built with Flask. This application helps farmers manage their goat herds with features for tracking health, breeding, vaccinations, weight monitoring, and more.

## Features

### 🐐 Goat Management
- **Goat Registration**: Add new goats with detailed information (tag, breed, sex, DOB, etc.)
- **Smart Tagging System**: Automatic status tags (pregnant, sick, underweight, ready to mate, etc.)
- **Weight Tracking**: Monitor goat weight over time with target weight comparisons
- **Photo Management**: Upload and manage goat photos and feedback images
- **Status Filtering**: Filter goats by various status tags for efficient management

### 🏥 Health Management
- **Sickness Tracking**: Record and monitor goat illnesses with photos
- **Medicine Administration**: Track treatments and medications
- **Health Reports**: Generate comprehensive health status reports
- **Recovery Tracking**: Mark goats as recovered and track health history

### 💉 Vaccination Management
- **Vaccine Types**: Manage different vaccine types and schedules
- **Vaccination Events**: Record and track vaccination history
- **Due Date Tracking**: Automatic alerts for upcoming and overdue vaccinations
- **Batch Vaccination**: Efficiently vaccinate multiple goats at once
- **Compliance Reports**: Generate vaccination compliance reports

### 🐑 Breeding Management
- **Breeding Events**: Track mating events and breeding history
- **Pregnancy Tracking**: Monitor pregnant does and expected delivery dates
- **Ready Does**: Identify does ready for breeding
- **Breeding Reports**: Generate breeding performance reports

### 📊 Dashboard & Analytics
- **Farm Overview**: Real-time statistics and key metrics
- **Visual Charts**: Goat distribution by type, health status, and more
- **Quick Entry**: Rapid data entry for weights, vaccinations, and health updates
- **Performance Metrics**: Track farm performance indicators

### 📅 Calendar & Events
- **Event Management**: Schedule and track farm events
- **Recurring Events**: Set up repeating events (daily, weekly, monthly)
- **Vaccination Reminders**: Automatic calendar integration for vaccine schedules
- **Event Categories**: Organize events by type and priority

### 📈 Reports & Analytics
- **Health Reports**: Comprehensive health status and trends
- **Vaccination Reports**: Compliance and schedule tracking
- **Goat Register**: Complete goat inventory reports
- **PDF Export**: Generate professional PDF reports
- **Email Reports**: Send reports via email

### 👥 User Management
- **Role-Based Access**: Admin, Worker, and Superadmin roles
- **User Profiles**: Manage user information and permissions
- **Password Management**: Secure password reset and change functionality
- **Activity Tracking**: Track user actions and changes

### ⚙️ Configuration
- **Farm Settings**: Configure farm-specific parameters
- **Target Weights**: Set target weights by breed, age, and sex
- **Vaccine Schedules**: Configure vaccination schedules
- **System Settings**: Customize application behavior

## Technology Stack

- **Backend**: Flask (Python web framework)
- **Database**: SQLite with SQLAlchemy ORM
- **Frontend**: HTML5, CSS3, JavaScript, Bootstrap 5
- **Authentication**: Session-based with role management
- **File Handling**: Secure file uploads for photos
- **Email**: Flask-Mail for notifications
- **PDF Generation**: pdfkit for report generation
- **Database Migrations**: Flask-Migrate

## Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package installer)
- wkhtmltopdf (for PDF generation)

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd goat-manager-app-blueprint-ver1
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   
   # On Windows
   venv\Scripts\activate
   
   # On macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install wkhtmltopdf** (for PDF generation)
   - **Windows**: Download from [wkhtmltopdf.org](https://wkhtmltopdf.org/downloads.html)
   - **macOS**: `brew install wkhtmltopdf`
   - **Ubuntu/Debian**: `sudo apt-get install wkhtmltopdf`

5. **Configure environment variables** (optional)
   Create a `.env` file in the root directory:
   ```env
   SECRET_KEY=your-secret-key-here
   MAIL_USERNAME=your-email@gmail.com
   MAIL_PASSWORD=your-app-password
   ```

6. **Initialize the database**
   ```bash
   flask db init
   flask db migrate -m "Initial migration"
   flask db upgrade
   ```

7. **Load sample data** (optional)
   ```bash
   python init_mock_data.py
   ```

8. **Run the application**
   ```bash
   python run.py
   ```

9. **Access the application**
   Open your browser and navigate to `http://localhost:5000`

## Default Login Credentials

After running `init_mock_data.py`, you can use these default accounts:

- **Superadmin**: 
  - Username: `superadmin`
  - Password: `password`

- **Admin**: 
  - Username: `admin`
  - Password: `password`

- **Worker**: 
  - Username: `worker`
  - Password: `password`

**⚠️ Important**: Change these default passwords immediately in production!

## Configuration

### Email Configuration
Update the email settings in `config.py`:
```python
MAIL_SERVER = 'smtp.gmail.com'
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = 'your_email@gmail.com'
MAIL_PASSWORD = 'your_app_password'
```

### Database Configuration
The application uses SQLite by default. To use a different database, update the `SQLALCHEMY_DATABASE_URI` in `config.py`.

## Project Structure

```
goat-manager-app-blueprint-ver1/
├── app/
│   ├── __init__.py              # Application factory
│   ├── models.py                # Database models
│   ├── utils.py                 # Utility functions
│   ├── extensions.py            # Flask extensions
│   └── blueprints/              # Application blueprints
│       ├── auth/                # Authentication
│       ├── dashboard/           # Dashboard and main views
│       ├── goats/              # Goat management
│       ├── breeding/           # Breeding management
│       ├── vaccine/            # Vaccination management
│       ├── sickness/           # Health management
│       ├── reports/            # Reports and analytics
│       ├── users/              # User management
│       └── calendar/           # Calendar and events
├── templates/                   # HTML templates
├── static/                     # Static files (CSS, JS, images)
├── migrations/                 # Database migrations
├── instance/                   # Instance-specific files
├── config.py                   # Configuration settings
├── run.py                      # Application entry point
├── init_mock_data.py          # Sample data loader
└── requirements.txt           # Python dependencies
```

## Key Features Explained

### Smart Tagging System
The application automatically generates status tags for goats based on various conditions:
- **Pregnant**: Manually marked pregnant goats
- **Sick**: Goats with active sickness records
- **Underweight**: Goats below target weight for their age/breed
- **Ready to Mate**: Eligible female goats for breeding
- **Old**: Goats over 6 years old
- **New Arrival**: Recently acquired goats (first 60 days)
- **New Born**: Recently born goats (first 60 days)
- **Matured**: Goats over 1 year old

### Target Weight System
Set and manage target weights based on:
- Goat breed/type
- Age in months
- Sex (Male/Female or All)

### Vaccination Scheduling
Automatic tracking of:
- Due vaccinations
- Overdue vaccinations
- Vaccination history
- Compliance reporting

## API Endpoints

The application provides several AJAX endpoints for dynamic functionality:
- `/vaccine/get_due_info/<goat_id>` - Get vaccination due information
- `/goats/api/goats` - Get goat data for filtering
- Calendar event management endpoints

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Commit your changes (`git commit -am 'Add new feature'`)
4. Push to the branch (`git push origin feature/new-feature`)
5. Create a Pull Request

## Security Considerations

- Change default passwords immediately
- Use strong SECRET_KEY in production
- Configure proper email credentials
- Implement HTTPS in production
- Regular database backups
- User input validation and sanitization

## Troubleshooting

### Common Issues

1. **PDF Generation Fails**
   - Ensure wkhtmltopdf is installed and in PATH
   - Check file permissions for static/uploads directory

2. **Email Not Working**
   - Verify email configuration in config.py
   - Check Gmail app password settings
   - Ensure less secure app access is enabled

3. **Database Errors**
   - Run `flask db upgrade` to apply migrations
   - Check database file permissions

4. **File Upload Issues**
   - Ensure static/uploads directory exists
   - Check directory write permissions

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:
- Create an issue in the repository
- Check the troubleshooting section
- Review the configuration settings

## Changelog

### Version 1.0.0
- Initial release with core goat management features
- Smart tagging system implementation
- Comprehensive vaccination management
- Health tracking and reporting
- User role management
- Calendar integration
- PDF report generation
